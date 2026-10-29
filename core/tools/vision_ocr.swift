// vision_ocr: PDF text and OCR with macOS's own frameworks (PDFKit + Vision). No cloud, no cost.
// Used by core/tools/docs.py (staff-docs), which compiles it once with swiftc and caches the binary.
//
//   vision_ocr text  <file.pdf> [--pages 1-3,7]            the PDF's text layer, page by page
//   vision_ocr ocr   <file.pdf|image> [--pages 1-3] [--langs ar,en] [--dpi 200] [--sep "  "]
//   vision_ocr info  <file.pdf>                            page count, text characters per page
//   vision_ocr langs                                       languages Vision can read on this Mac
//
// Output is UTF-8, one "===== page N =====" header per page. OCR lines are rebuilt from Vision's
// boxes: top to bottom; right to left on lines that are mostly Arabic/Hebrew script, else left to
// right; separate boxes on one line joined with --sep (" | " turns a scanned table into rows).
import AppKit
import CoreGraphics
import Foundation
import PDFKit
import Vision

func fail(_ msg: String, _ code: Int32 = 1) -> Never {
    FileHandle.standardError.write((msg + "\n").data(using: .utf8)!)
    exit(code)
}

func out(_ s: String) {
    FileHandle.standardOutput.write((s + "\n").data(using: .utf8)!)
}

var args = Array(CommandLine.arguments.dropFirst())
if args.isEmpty { fail("usage: vision_ocr text|ocr|info|langs <file> [--pages 1-3] [--langs ar,en] [--dpi 200] [--sep S]", 2) }
let mode = args.removeFirst()
var pagesSpec: String? = nil
var langArg: [String] = []
var dpi: Double = 200
var sep = "  "
var path: String? = nil
var i = 0
while i < args.count {
    let a = args[i]
    func next() -> String { if i + 1 < args.count { i += 1; return args[i] }; fail("\(a) needs a value", 2) }
    switch a {
    case "--pages": pagesSpec = next()
    case "--langs": langArg = next().split(separator: ",").map { String($0).trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }
    case "--dpi": dpi = max(72, min(400, Double(next()) ?? 200))
    case "--sep": sep = next()
    default: path = a
    }
    i += 1
}

func pageList(_ spec: String?, _ count: Int) -> [Int] {
    guard let spec = spec, !spec.isEmpty else { return Array(stride(from: 1, through: count, by: 1)) }
    var pages: [Int] = []
    for part in spec.split(separator: ",") {
        let ends = part.split(separator: "-").map { Int($0.trimmingCharacters(in: .whitespaces)) ?? 0 }
        let lo = ends.first ?? 1, hi = ends.last ?? lo
        if lo < 1 || hi < lo { continue }
        for p in lo...min(hi, count) where !pages.contains(p) { pages.append(p) }
    }
    return pages
}

func supported() -> [String] {
    let req = VNRecognizeTextRequest()
    req.recognitionLevel = .accurate
    if #available(macOS 13.0, *) { req.revision = VNRecognizeTextRequestRevision3 }
    return (try? req.supportedRecognitionLanguages()) ?? ["en-US"]
}

// "ar" -> "ar-SA", "zh" -> "zh-Hans"... anything Vision lists that starts with the code.
func resolveLangs(_ wanted: [String]) -> [String] {
    let sup = supported()
    var outLangs: [String] = []
    for w in wanted {
        let lw = w.lowercased()
        if let exact = sup.first(where: { $0.lowercased() == lw }) { outLangs.append(exact); continue }
        for s in sup where s.lowercased().hasPrefix(lw + "-") && !outLangs.contains(s) { outLangs.append(s) }
    }
    return outLangs
}

func isRTL(_ s: String) -> Bool {
    var rtl = 0, ltr = 0
    for u in s.unicodeScalars {
        switch u.value {
        case 0x0590...0x08FF, 0xFB1D...0xFDFF, 0xFE70...0xFEFF: rtl += 1
        case 0x0041...0x005A, 0x0061...0x007A, 0x00C0...0x024F, 0x0400...0x04FF: ltr += 1
        default: break
        }
    }
    return rtl > ltr
}

struct Box { let text: String; let r: CGRect }

func layout(_ boxes: [Box]) -> [String] {
    let sorted = boxes.sorted { $0.r.midY > $1.r.midY }
    var lines: [[Box]] = []
    for b in sorted {
        if var last = lines.last, let ref = last.first {
            let tol = min(ref.r.height, b.r.height) * 0.6
            if abs(ref.r.midY - b.r.midY) <= tol {
                last.append(b)
                lines[lines.count - 1] = last
                continue
            }
        }
        lines.append([b])
    }
    return lines.map { line in
        let rtl = isRTL(line.map { $0.text }.joined())
        let ordered = line.sorted { rtl ? $0.r.minX > $1.r.minX : $0.r.minX < $1.r.minX }
        return ordered.map { $0.text }.joined(separator: sep)
    }
}

func recognize(_ cg: CGImage) -> [String] {
    let req = VNRecognizeTextRequest()
    req.recognitionLevel = .accurate
    req.usesLanguageCorrection = true
    if #available(macOS 13.0, *) { req.revision = VNRecognizeTextRequestRevision3 }
    if !langArg.isEmpty {
        let langs = resolveLangs(langArg)
        if langs.isEmpty { fail("none of \(langArg) is supported by Vision here; see: vision_ocr langs", 2) }
        req.recognitionLanguages = langs
        if #available(macOS 13.0, *) { req.automaticallyDetectsLanguage = false }
    } else if #available(macOS 13.0, *) {
        req.automaticallyDetectsLanguage = true
    }
    do {
        try VNImageRequestHandler(cgImage: cg, options: [:]).perform([req])
    } catch {
        fail("Vision failed: \(error.localizedDescription)")
    }
    let boxes: [Box] = (req.results ?? []).compactMap { o in
        guard let t = o.topCandidates(1).first?.string, !t.isEmpty else { return nil }
        return Box(text: t, r: o.boundingBox)
    }
    return layout(boxes)
}

func renderPage(_ page: PDFPage) -> CGImage? {
    var size = page.bounds(for: .mediaBox).size
    if page.rotation % 180 != 0 { size = CGSize(width: size.height, height: size.width) }
    var scale = dpi / 72.0
    let maxPixels = 40_000_000.0
    if Double(size.width) * Double(size.height) * scale * scale > maxPixels {
        scale = (maxPixels / (Double(size.width) * Double(size.height))).squareRoot()
    }
    let target = CGSize(width: Double(size.width) * scale, height: Double(size.height) * scale)
    let img = page.thumbnail(of: target, for: .mediaBox)
    var rect = CGRect(origin: .zero, size: img.size)
    return img.cgImage(forProposedRect: &rect, context: nil, hints: nil)
}

func openPDF(_ p: String) -> PDFDocument {
    guard let doc = PDFDocument(url: URL(fileURLWithPath: p)) else { fail("can't open \(p) as a PDF") }
    if doc.isLocked && !doc.unlock(withPassword: "") { fail("\(p) is password-protected") }
    return doc
}

if mode == "langs" {
    out(supported().joined(separator: "\n"))
    exit(0)
}
guard let file = path else { fail("no file given", 2) }
if !FileManager.default.fileExists(atPath: file) { fail("no such file: \(file)", 2) }
let isPDF = file.lowercased().hasSuffix(".pdf") || ((try? Data(contentsOf: URL(fileURLWithPath: file), options: .alwaysMapped))?.prefix(5) == Data("%PDF-".utf8))

switch mode {
case "info":
    let doc = openPDF(file)
    out("pages=\(doc.pageCount)")
    for n in 1...max(1, doc.pageCount) where n <= doc.pageCount {
        let chars = (doc.page(at: n - 1)?.string ?? "").trimmingCharacters(in: .whitespacesAndNewlines).count
        out("page \(n) chars=\(chars)")
    }
case "text":
    let doc = openPDF(file)
    for n in pageList(pagesSpec, doc.pageCount) {
        out("===== page \(n) =====")
        out(doc.page(at: n - 1)?.string ?? "")
    }
case "ocr":
    if isPDF {
        let doc = openPDF(file)
        for n in pageList(pagesSpec, doc.pageCount) {
            out("===== page \(n) =====")
            guard let page = doc.page(at: n - 1), let cg = renderPage(page) else { out("[page \(n) could not be rendered]"); continue }
            for line in recognize(cg) { out(line) }
        }
    } else {
        guard let img = NSImage(contentsOfFile: file) else { fail("can't load \(file) as an image") }
        var rect = CGRect(origin: .zero, size: img.size)
        guard let cg = img.cgImage(forProposedRect: &rect, context: nil, hints: nil) else { fail("can't decode \(file)") }
        out("===== page 1 =====")
        for line in recognize(cg) { out(line) }
    }
default:
    fail("unknown mode \(mode): text | ocr | info | langs", 2)
}
