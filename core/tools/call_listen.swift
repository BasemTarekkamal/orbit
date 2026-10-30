// Orbit Listener: captures what this Mac plays (the other side of a call) and its microphone (you),
// as two raw 16 kHz mono float32 files, until <dir>/stop appears, SIGTERM, or the time cap.
//
//   OrbitListener.app/Contents/MacOS/orbit-listen <dir> [--max-min 180] [--no-mic]
//
// Writes <dir>/them.pcm, <dir>/you.pcm, <dir>/listener.pid, and <dir>/error.txt (one plain line) on
// failure. Built into a tiny .app by core/calls.py so macOS asks permission for "Orbit Listener",
// not for Python. Uses ScreenCaptureKit (macOS 15+). Nothing leaves the Mac. No bot joins the call.
import AVFoundation
import CoreGraphics
import CoreMedia
import Foundation
import ScreenCaptureKit

let args = CommandLine.arguments
guard args.count >= 2 else {
    FileHandle.standardError.write("usage: orbit-listen <dir> [--max-min N] [--no-mic]\n".data(using: .utf8)!)
    exit(64)
}
let dir = URL(fileURLWithPath: args[1])
var maxMin = 180.0
if let i = args.firstIndex(of: "--max-min"), i + 1 < args.count, let v = Double(args[i + 1]) { maxMin = v }
let wantMic = !args.contains("--no-mic")
try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)

func fail(_ msg: String, _ code: Int32 = 2) -> Never {
    try? (msg + "\n").write(to: dir.appendingPathComponent("error.txt"), atomically: true, encoding: .utf8)
    FileHandle.standardError.write((msg + "\n").data(using: .utf8)!)
    exit(code)
}

/// Converts whatever ScreenCaptureKit delivers to 16 kHz mono float32 and appends it to a file.
final class Sink {
    let fh: FileHandle
    let out = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: 16000, channels: 1, interleaved: false)!
    var conv: AVAudioConverter?
    var inFmt: AVAudioFormat?

    init(_ name: String) {
        let p = dir.appendingPathComponent(name).path
        FileManager.default.createFile(atPath: p, contents: nil)
        fh = FileHandle(forWritingAtPath: p)!
    }

    func write(_ sb: CMSampleBuffer) {
        guard sb.isValid, let fd = CMSampleBufferGetFormatDescription(sb),
              let asbd = CMAudioFormatDescriptionGetStreamBasicDescription(fd),
              let fmt = AVAudioFormat(streamDescription: asbd) else { return }
        if inFmt == nil || inFmt! != fmt {
            inFmt = fmt
            conv = AVAudioConverter(from: fmt, to: out)
        }
        let n = AVAudioFrameCount(CMSampleBufferGetNumSamples(sb))
        guard n > 0, let conv = conv, let inBuf = AVAudioPCMBuffer(pcmFormat: fmt, frameCapacity: n) else { return }
        inBuf.frameLength = n
        guard CMSampleBufferCopyPCMDataIntoAudioBufferList(sb, at: 0, frameCount: Int32(n),
                                                           into: inBuf.mutableAudioBufferList) == noErr else { return }
        let cap = AVAudioFrameCount(Double(n) * out.sampleRate / fmt.sampleRate) + 64
        guard let o = AVAudioPCMBuffer(pcmFormat: out, frameCapacity: cap) else { return }
        var fed = false
        var err: NSError?
        conv.convert(to: o, error: &err) { _, status in
            if fed { status.pointee = .noDataNow; return nil }
            fed = true
            status.pointee = .haveData
            return inBuf
        }
        if o.frameLength > 0, let p = o.floatChannelData?[0] {
            fh.write(Data(bytes: p, count: Int(o.frameLength) * MemoryLayout<Float>.size))
        }
    }
}

final class Capture: NSObject, SCStreamOutput, SCStreamDelegate {
    let them = Sink("them.pcm")
    let you = Sink("you.pcm")

    func stream(_ stream: SCStream, didOutputSampleBuffer sb: CMSampleBuffer, of type: SCStreamOutputType) {
        switch type {
        case .audio: them.write(sb)
        case .microphone: you.write(sb)
        default: break
        }
    }

    func stream(_ stream: SCStream, didStopWithError error: Error) {
        fail("Listening stopped: \(error.localizedDescription)", 3)
    }
}

let cap = Capture()
var stream: SCStream?

func finish() -> Never {
    let sem = DispatchSemaphore(value: 0)
    if let s = stream {
        s.stopCapture { _ in sem.signal() }
        _ = sem.wait(timeout: .now() + 3)
    }
    try? cap.them.fh.close()
    try? cap.you.fh.close()
    try? FileManager.default.removeItem(at: dir.appendingPathComponent("listener.pid"))
    exit(0)
}

signal(SIGTERM, SIG_IGN)
signal(SIGINT, SIG_IGN)
let sigs = [SIGTERM, SIGINT].map { DispatchSource.makeSignalSource(signal: $0, queue: .main) }
for s in sigs { s.setEventHandler { finish() }; s.resume() }

Task {
    if wantMic {                                               // ask for both on the first try, mic first
        let asking = dir.appendingPathComponent("asking.txt")
        if AVCaptureDevice.authorizationStatus(for: .audio) == .notDetermined {
            try? "microphone".write(to: asking, atomically: true, encoding: .utf8)
        }
        let ok = await AVCaptureDevice.requestAccess(for: .audio)
        try? FileManager.default.removeItem(at: asking)
        if !ok {
            fail("NEEDS_PERMISSION microphone: turn on Orbit Listener in System Settings > Privacy & Security > "
                 + "Microphone, then start again.")
        }
    }
    if !CGPreflightScreenCaptureAccess() {
        CGRequestScreenCaptureAccess()
        fail("NEEDS_PERMISSION screen: turn on Orbit Listener in System Settings > Privacy & Security > "
             + "Screen & System Audio Recording, then start again.")
    }
    do {
        let content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: true)
        guard let display = content.displays.first else { fail("No display found to attach audio capture to.") }
        let cfg = SCStreamConfiguration()
        cfg.capturesAudio = true
        cfg.excludesCurrentProcessAudio = true
        cfg.sampleRate = 48000
        cfg.channelCount = 1
        cfg.captureMicrophone = wantMic
        cfg.width = 2                                          // audio only: keep the video side tiny
        cfg.height = 2
        cfg.minimumFrameInterval = CMTime(value: 1, timescale: 1)
        let filter = SCContentFilter(display: display, excludingApplications: [], exceptingWindows: [])
        let s = SCStream(filter: filter, configuration: cfg, delegate: cap)
        let q = DispatchQueue(label: "orbit.listen.audio")
        try s.addStreamOutput(cap, type: .audio, sampleHandlerQueue: q)
        if wantMic { try s.addStreamOutput(cap, type: .microphone, sampleHandlerQueue: q) }
        try s.addStreamOutput(cap, type: .screen, sampleHandlerQueue: DispatchQueue(label: "orbit.listen.video"))
        try await s.startCapture()
        stream = s
    } catch {
        let msg = error.localizedDescription
        if msg.lowercased().contains("declined") || msg.lowercased().contains("permission") {
            fail("NEEDS_PERMISSION screen: turn on Orbit Listener in System Settings > Privacy & Security > "
                 + "Screen & System Audio Recording, then start again.")
        }
        fail("Couldn't start listening: \(msg)")
    }
    try? String(getpid()).write(to: dir.appendingPathComponent("listener.pid"), atomically: true, encoding: .utf8)
}

let started = Date()
let stopFile = dir.appendingPathComponent("stop").path
Timer.scheduledTimer(withTimeInterval: 0.5, repeats: true) { _ in
    if FileManager.default.fileExists(atPath: stopFile) || Date().timeIntervalSince(started) > maxMin * 60 {
        finish()
    }
}
RunLoop.main.run()
