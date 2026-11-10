import Cocoa

// Each application activation as the window server reports it, one line as it happens:
// `epoch_ms<TAB>name<TAB>pid`, after one `epoch_ms<TAB>LISTENING<TAB>name<TAB>pid` naming who is
// in front as it begins. It ends when its stdin does, so it never outlives the run that started it.
setvbuf(stdout, nil, _IOLBF, 0)

func nowMs() -> Int { Int(Date().timeIntervalSince1970 * 1000) }

func named(_ app: NSRunningApplication?) -> String {
    let name = (app?.localizedName ?? app?.executableURL?.lastPathComponent ?? "")
        .components(separatedBy: .controlCharacters).joined(separator: " ")
    return "\(name)\t\(app?.processIdentifier ?? -1)"
}

NSWorkspace.shared.notificationCenter.addObserver(
    forName: NSWorkspace.didActivateApplicationNotification, object: nil, queue: nil
) { note in
    let app = note.userInfo?[NSWorkspace.applicationUserInfoKey] as? NSRunningApplication
    print("\(nowMs())\t\(named(app))")
}
Thread.detachNewThread {
    while readLine() != nil {}
    exit(0)
}
print("\(nowMs())\tLISTENING\t\(named(NSWorkspace.shared.frontmostApplication))")
RunLoop.main.run()
