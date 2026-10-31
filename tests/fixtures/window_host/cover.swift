import Cocoa
class D: NSObject, NSApplicationDelegate {
  var w: NSWindow!
  func applicationDidFinishLaunching(_ n: Notification) {
    w = NSWindow(contentRect: NSRect(x: 100, y: 100, width: 600, height: 400), styleMask: [.titled, .resizable, .closable], backing: .buffered, defer: false)
    w.title = "scry-cover"
    w.collectionBehavior = [.fullScreenPrimary]
    w.makeKeyAndOrderFront(nil)
    NSApp.activate(ignoringOtherApps: true)
    DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { self.w.toggleFullScreen(nil) }
  }
}
let app = NSApplication.shared
let d = D(); app.delegate = d
app.setActivationPolicy(.regular)
app.run()
