import Cocoa

// Takes the front for the milliseconds its argument says, then exits: a theft made on purpose.
let hold = Double(CommandLine.arguments[1])! / 1000
let app = NSApplication.shared
app.setActivationPolicy(.regular)
let w = NSWindow(contentRect: NSRect(x: 300, y: 300, width: 300, height: 200), styleMask: [.titled], backing: .buffered, defer: false)
w.title = "scry-thief"
NotificationCenter.default.addObserver(
    forName: NSApplication.didBecomeActiveNotification, object: nil, queue: nil
) { _ in
    DispatchQueue.main.asyncAfter(deadline: .now() + hold) { exit(0) }
}
DispatchQueue.main.asyncAfter(deadline: .now() + 6) { exit(2) }
w.makeKeyAndOrderFront(nil)
app.activate(ignoringOtherApps: true)
app.run()
