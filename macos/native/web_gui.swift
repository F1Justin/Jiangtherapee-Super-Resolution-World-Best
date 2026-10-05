import AppKit
import WebKit

final class Host: NSObject, NSApplicationDelegate, WKScriptMessageHandlerWithReply, WKNavigationDelegate, NSWindowDelegate {
    var window: NSWindow!
    var web: WKWebView!
    var worker = Process()
    var input = Pipe()
    var output = Pipe()
    var callbacks: [Int: (Any?, String?) -> Void] = [:]
    var nextID = 0
    var outputFolder: String?
    let arguments = CommandLine.arguments
    var resources: URL {
        if let i = arguments.firstIndex(of: "--resources"), arguments.count > i + 1 { return URL(fileURLWithPath: arguments[i + 1]) }
        return Bundle.main.bundleURL.appendingPathComponent("Contents/Resources")
    }
    var testing: Bool { arguments.contains("--self-test") || arguments.contains("--structure-test") }
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        let menu = NSMenu()
        let item = NSMenuItem(); menu.addItem(item)
        let submenu = NSMenu(); submenu.addItem(withTitle: "退出 JSR Bridge", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        item.submenu = submenu; NSApp.mainMenu = menu
        let configuration = WKWebViewConfiguration()
        configuration.userContentController.addScriptMessageHandler(self, contentWorld: .page, name: "vault")
        web = WKWebView(frame: .zero, configuration: configuration)
        web.navigationDelegate = self
        web.isInspectable = false
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1280, height: 850), styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "Jiangtherapee Bridge · Apple Silicon / Metal"
        window.minSize = NSSize(width: 920, height: 650)
        window.contentView = web; window.delegate = self; window.center(); window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        let bundled = Bundle.main.bundleURL.appendingPathComponent("Contents/MacOS/jsr-cli")
        if FileManager.default.isExecutableFile(atPath: bundled.path) {
            worker.executableURL = bundled; worker.arguments = ["web-worker"]
        } else {
            let i = arguments.firstIndex(of: "--engine-root")
            let root = i == nil ? resources.deletingLastPathComponent() : URL(fileURLWithPath: arguments[i! + 1])
            worker.executableURL = root.appendingPathComponent(".venv/bin/python")
            worker.arguments = ["-u", root.appendingPathComponent("web_bridge.py").path]
        }
        worker.standardInput = input; worker.standardOutput = output; worker.standardError = FileHandle.standardError
        do { try worker.run() } catch { fatalError("Backend: \(error)") }
        DispatchQueue.global(qos: .userInitiated).async {
            var buffer = Data()
            while true {
                let chunk = self.output.fileHandleForReading.availableData
                if chunk.isEmpty { break }
                buffer.append(chunk)
                while let end = buffer.firstIndex(of: 10) {
                    let line = buffer[..<end]; buffer.removeSubrange(...end)
                    guard let value = try? JSONSerialization.jsonObject(with: line) as? [String: Any], let id = value["id"] as? Int else { continue }
                    DispatchQueue.main.async {
                        let callback = self.callbacks.removeValue(forKey: id)
                        callback?(value["result"], value["error"] as? String)
                    }
                }
            }
            DispatchQueue.main.async {
                let pending = self.callbacks; self.callbacks.removeAll()
                for callback in pending.values { callback(nil, "计算服务已退出") }
            }
        }
        let page = resources.appendingPathComponent("web/index.html")
        web.loadFileURL(page, allowingReadAccessTo: page.deletingLastPathComponent())
        if testing { DispatchQueue.main.asyncAfter(deadline: .now() + 600) { self.fail("GUI test timeout") } }
    }
    func forward(_ route: String, _ payload: [String: Any], _ reply: @escaping (Any?, String?) -> Void) {
        nextID += 1; let id = nextID; callbacks[id] = reply
        do {
            var data = try JSONSerialization.data(withJSONObject: ["id": id, "route": route, "payload": payload])
            data.append(10); try input.fileHandleForWriting.write(contentsOf: data)
        } catch { callbacks.removeValue(forKey: id); reply(nil, String(describing: error)) }
    }
    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage, replyHandler: @escaping (Any?, String?) -> Void) {
        guard message.frameInfo.isMainFrame, message.frameInfo.request.url?.isFileURL == true,
              let body = message.body as? [String: Any], let route = body["route"] as? String else { replyHandler(nil, "请求来源无效"); return }
        var payload = body["payload"] as? [String: Any] ?? [:]
        if route == "author" {
            web.evaluateJavaScript("document.querySelector('#author-support').showModal()")
            replyHandler([:], nil); return
        }
        if route == "jsr/select" && payload["paths"] == nil {
            if testing, let i = arguments.firstIndex(of: "--fixtures"), arguments.count > i + 1 {
                let folder = URL(fileURLWithPath: arguments[i + 1])
                let files = (try? FileManager.default.contentsOfDirectory(at: folder, includingPropertiesForKeys: nil)) ?? []
                let count = (payload["engine"] as? String) == "stormer7" ? 7 : 14
                payload["paths"] = Array(files.filter { ["nef", "dng"].contains($0.pathExtension.lowercased()) }.sorted { $0.path < $1.path }.prefix(count)).map { $0.path }
            } else {
                let panel = NSOpenPanel(); panel.allowsMultipleSelection = payload["folder"] as? Bool != true
                panel.canChooseDirectories = payload["folder"] as? Bool == true; panel.canChooseFiles = !panel.canChooseDirectories
                panel.title = "选择 RAW 文件"
                guard panel.runModal() == .OK else { replyHandler(NSNull(), nil); return }
                if panel.canChooseDirectories {
                    let files = (try? FileManager.default.contentsOfDirectory(at: panel.url!, includingPropertiesForKeys: nil)) ?? []
                    payload["paths"] = files.filter { ["nef", "arw", "cr2", "cr3", "dng", "raf", "rw2", "orf", "pef", "srw", "nrw"].contains($0.pathExtension.lowercased()) }.sorted { $0.path < $1.path }.map { $0.path }
                } else { payload["paths"] = panel.urls.map { $0.path } }
            }
        }
        if route == "pick" || route == "jsr/dark" {
            let panel = NSOpenPanel(); panel.canChooseDirectories = route == "pick"; panel.canChooseFiles = route == "jsr/dark"; panel.allowsMultipleSelection = false
            replyHandler(["path": panel.runModal() == .OK ? panel.url!.path : ""], nil); return
        }
        if route == "jsr/reveal" {
            if let path = outputFolder { NSWorkspace.shared.open(URL(fileURLWithPath: path)) }
            replyHandler([:], nil); return
        }
        let allowed = ["jsr/select", "jsr/options", "jsr/start", "jsr/status", "jsr/cancel"]
        guard allowed.contains(route) else { replyHandler(nil, "未知请求"); return }
        forward(route, payload) { result, error in
            if route == "jsr/start", let value = result as? [String: Any] { self.outputFolder = value["output"] as? String }
            replyHandler(result, error)
        }
    }
    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        guard testing else { return }
        Task { @MainActor in
            do {
                let body = self.arguments.contains("--structure-test") ? "return {host:'WKWebView',modes:document.querySelectorAll('[data-engine]').length,ui:!!document.querySelector('#jsr-start'),author:!!document.querySelector('#author-support img'),errors:document.querySelector('#mac-error').textContent};" : "return await window.macSelfTest(runJob);"
                let value = try await webView.callAsyncJavaScript(body, arguments: ["runJob": self.arguments.contains("--job-test")], in: nil, contentWorld: .page)
                let data = try JSONSerialization.data(withJSONObject: value!, options: [.sortedKeys])
                print(String(data: data, encoding: .utf8)!)
                if let i = self.arguments.firstIndex(of: "--snapshot"), self.arguments.count > i + 1 {
                    webView.takeSnapshot(with: nil) { image, error in
                        if let image = image, let tiff = image.tiffRepresentation, let bitmap = NSBitmapImageRep(data: tiff), let png = bitmap.representation(using: .png, properties: [:]) {
                            try? png.write(to: URL(fileURLWithPath: self.arguments[i + 1]))
                        }
                        NSApp.terminate(nil)
                    }
                } else { NSApp.terminate(nil) }
            } catch { self.fail(String(describing: error)) }
        }
    }

    func fail(_ message: String) { fputs(message + "\n", stderr); cleanup(); exit(1) }
    func cleanup() {
        input.fileHandleForWriting.closeFile()
        if worker.isRunning { worker.waitUntilExit() }
    }
    func applicationWillTerminate(_ notification: Notification) { cleanup() }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        decisionHandler(navigationAction.request.url?.isFileURL == true ? .allow : .cancel)
    }
}
let delegate = Host()
NSApplication.shared.delegate = delegate
NSApplication.shared.run()
