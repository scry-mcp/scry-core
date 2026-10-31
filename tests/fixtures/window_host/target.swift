import Cocoa
let app = NSApplication.shared
app.setActivationPolicy(.regular)
let w = NSWindow(contentRect: NSRect(x: 300, y: 300, width: 400, height: 300), styleMask: [.titled], backing: .buffered, defer: false)
w.title = "scry-target"
w.makeKeyAndOrderFront(nil)
app.run()
