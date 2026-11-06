// External, user-run read-only probe. Never grants TCC permissions or synthesizes input.
import Cocoa
import ApplicationServices

func attribute(_ element: AXUIElement, _ name: String) -> CFTypeRef? {
    var value: CFTypeRef?
    guard AXUIElementCopyAttributeValue(element, name as CFString, &value) == .success else { return nil }
    return value
}

func text(_ element: AXUIElement, _ name: String) -> String {
    guard let value = attribute(element, name) else { return "" }
    return String(String(describing: value).prefix(800))
}

func children(_ element: AXUIElement) -> [AXUIElement] {
    return attribute(element, kAXChildrenAttribute) as? [AXUIElement] ?? []
}

var remaining = 4000
var truncatedReasons = Set<String>()
var unreadableElements = 0
func snapshot(_ element: AXUIElement, _ path: [Int], _ depth: Int) -> [String: Any] {
    remaining -= 1
    let role = text(element, kAXRoleAttribute)
    let rawValue = attribute(element, kAXValueAttribute).map { String(describing: $0) } ?? ""
    if role.isEmpty { unreadableElements += 1 }
    var actions: CFArray?
    AXUIElementCopyActionNames(element, &actions)
    var valueSettable = DarwinBoolean(false)
    AXUIElementIsAttributeSettable(element, kAXValueAttribute as CFString, &valueSettable)
    var node: [String: Any] = [
        "path": path, "role": role,
        "title": text(element, kAXTitleAttribute),
        "description": text(element, kAXDescriptionAttribute),
        "identifier": text(element, kAXIdentifierAttribute),
        "value": text(element, kAXValueAttribute),
        "value_truncated": rawValue.count > 800,
        "value_settable": valueSettable.boolValue,
        "enabled": attribute(element, kAXEnabledAttribute) as? Bool ?? false,
        "actions": actions as? [String] ?? []
    ]
    let descendants = children(element)
    node["child_count"] = descendants.count
    if depth >= 48 && !descendants.isEmpty { truncatedReasons.insert("depth_limit") }
    if depth < 48 && remaining > 0 {
        var entries: [[String: Any]] = []
        for (index, child) in descendants.enumerated() {
            if remaining <= 0 { truncatedReasons.insert("node_limit"); break }
            entries.append(snapshot(child, path + [index], depth + 1))
        }
        node["children"] = entries
    }
    return node
}

func emit(_ result: [String: Any], code: Int32 = 0) -> Never {
    if let data = try? JSONSerialization.data(withJSONObject: result, options: [.sortedKeys, .prettyPrinted]),
       let output = String(data: data, encoding: .utf8) { print(output) }
    exit(code)
}

guard AXIsProcessTrusted() else {
    emit(["ok": false, "error": "accessibility_not_granted",
          "note": "No permission change attempted. Enable your terminal in Privacy & Security > Device Control and Data Access (macOS 27), or Accessibility (earlier macOS)."], code: 2)
}
let matches = NSRunningApplication.runningApplications(withBundleIdentifier: "com.openai.codex")
guard matches.count == 1, let app = matches.first else {
    emit(["ok": false, "error": "Expected exactly one running ChatGPT/Codex application"], code: 3)
}
let application = AXUIElementCreateApplication(app.processIdentifier)
guard let windows = attribute(application, kAXWindowsAttribute) as? [AXUIElement], !windows.isEmpty else {
    emit(["ok": false, "error": "No accessible app windows; Electron AX availability unverified"], code: 4)
}
let requestedTitle = CommandLine.arguments.dropFirst().first
let selected = windows.filter { requestedTitle == nil || text($0, kAXTitleAttribute) == requestedTitle }
if requestedTitle != nil && selected.count != 1 {
    emit(["ok": false, "error": "Expected a unique exact window title"], code: 5)
}
var trees: [[String: Any]] = []
for (index, window) in selected.enumerated() {
    if remaining <= 0 { truncatedReasons.insert("node_limit"); break }
    trees.append(snapshot(window, [index], 0))
}
emit(["ok": true, "bundle_id": "com.openai.codex", "pid": app.processIdentifier,
      "read_only": true, "truncated": !truncatedReasons.isEmpty,
      "incomplete": !truncatedReasons.isEmpty || unreadableElements > 0,
      "unreadable_elements": unreadableElements,
      "truncation_reasons": Array(truncatedReasons).sorted(), "windows": trees,
      "note": "Paths are snapshot-local, not durable IDs. Values capped at 800 characters; depth capped at 48; node budget 4000." ])
