// User-run picker experiments and explicit nonce-bound harmless send-test.
import Cocoa
import ApplicationServices
import CryptoKit

struct ProbeFailure: Error { let message: String }
var failureContext: [String: Any] = [:]
struct Node {
    let identity = UUID()
    let element: AXUIElement?
    let role: String
    let title: String
    let value: String
    let enabled: Bool
    let actions: [String]
    let children: [Node]
    var all: [Node] { [self] + children.flatMap { $0.all } }
}

// Only the fully specified prose rendering observed in saved AX evidence is allowed.
// Never normalize observed text, indentation, trailing spaces, code or request IDs.
func promptMatches(_ observed: String, expected: String) -> Bool {
    if observed == expected { return true }
    let lines = expected.components(separatedBy: "\n")
    guard !expected.contains("`"), !expected.contains("~~~"), !expected.contains("\r"),
          !lines.contains(where: { !$0.isEmpty && ($0.hasPrefix(" ") || $0.hasPrefix("\t") || $0.hasSuffix(" ") || $0.hasSuffix("\t")) })
    else { return false }
    let rendered = lines.filter { !$0.isEmpty }.map {
        $0.hasPrefix("- ") ? "• " + $0.dropFirst(2) : $0
    }.joined(separator: "\n")
    return observed == rendered
}

func splitPromptMatches(_ values: [String], expected: String) -> Bool {
    let lines = expected.components(separatedBy: "\n")
    guard !expected.contains("`"), !expected.contains("~~~"), !expected.contains("\r"),
          !lines.contains(where: { !$0.isEmpty && ($0.hasPrefix(" ") || $0.hasPrefix("\t") || $0.hasSuffix(" ") || $0.hasSuffix("\t")) }) else { return false }
    let target = lines.filter { !$0.isEmpty }.map { $0.hasPrefix("- ") ? "• " + $0.dropFirst(2) : $0 }.joined(separator: "\n")
    let targetChars = Array(target)
    var offsets: Set<Int> = [0]
    for (index, value) in values.enumerated() {
        guard !value.isEmpty else { return false }
        var next: Set<Int> = []
        for offset in offsets {
            for seam in index == 0 ? [""] : ["", "\n"] {
                let piece = Array(seam + value)
                if offset + piece.count <= targetChars.count && Array(targetChars[offset..<(offset + piece.count)]) == piece {
                    next.insert(offset + piece.count)
                }
            }
        }
        offsets = next
        if offsets.isEmpty { return false }
    }
    return offsets.contains(targetChars.count)
}

func submittedPromptAnchors(_ root: Node, prompt: String) -> [Node] {
    var anchors: [UUID: Node] = [:]
    for node in root.all where node.role == "AXStaticText" && node.children.isEmpty && promptMatches(node.value, expected: prompt) {
        anchors[node.identity] = node
    }
    func leaves(_ node: Node) -> [Node]? {
        guard ["AXGroup", "AXList", "AXListMarker", "AXStaticText"].contains(node.role) else { return nil }
        if node.children.isEmpty { return ["AXStaticText", "AXListMarker"].contains(node.role) ? [node] : [] }
        var output: [Node] = []
        for child in node.children {
            guard let found = leaves(child) else { return nil }
            output += found
        }
        return output
    }
    func bodies(_ node: Node) {
        if let found = leaves(node), let last = found.last, splitPromptMatches(found.map { $0.value }, expected: prompt) {
            anchors[last.identity] = last
        }
        for child in node.children { bodies(child) }
    }
    for node in root.all where node.children.count >= 2 {
        for index in 0..<(node.children.count - 1) {
            let child = node.children[index]
            if child.role == "AXHeading" && child.title == "You said:" { bodies(node.children[index + 1]) }
        }
    }
    return Array(anchors.values)
}

func fail(_ message: String) throws -> Never { throw ProbeFailure(message: message) }
func spatialRoles(_ targetRole: String) -> Set<String> {
    // Open menu items occupy a layer above the composer and other app controls.
    if targetRole == "AXMenuItem" { return ["AXMenuItem"] }
    return ["AXButton", "AXPopUpButton", "AXMenuItem", "AXTextArea", "AXCheckBox", "AXRadioButton", "AXLink"]
}
func attribute(_ element: AXUIElement, _ name: String) -> CFTypeRef? {
    var value: CFTypeRef?
    guard AXUIElementCopyAttributeValue(element, name as CFString, &value) == .success else { return nil }
    return value
}
func string(_ element: AXUIElement, _ name: String) -> String {
    attribute(element, name) as? String ?? ""
}
func read(_ element: AXUIElement, depth: Int = 0, budget: inout Int) throws -> Node {
    guard budget > 0 else { try fail("node_limit") }
    budget -= 1
    let role = string(element, kAXRoleAttribute)
    guard !role.isEmpty else { try fail("unreadable_element") }
    let children = attribute(element, kAXChildrenAttribute) as? [AXUIElement] ?? []
    guard depth < 48 || children.isEmpty else { try fail("depth_limit") }
    var actionNames: CFArray?
    AXUIElementCopyActionNames(element, &actionNames)
    return Node(element: element, role: role, title: string(element, kAXTitleAttribute),
                value: string(element, kAXValueAttribute),
                enabled: attribute(element, kAXEnabledAttribute) as? Bool ?? false,
                actions: actionNames as? [String] ?? [],
                children: try children.map { try read($0, depth: depth + 1, budget: &budget) })
}

struct PriorTurn { let prompt: String; let endMarker: String }
var priorTurn: PriorTurn? = nil

func verifyPriorBinding(_ root: Node, prior: PriorTurn) throws {
    func scope(_ node: Node) -> Node? {
        let nodes = node.all
        guard submittedPromptAnchors(node, prompt: prior.prompt).count == 1,
              nodes.filter({ $0.role == "AXTextArea" && $0.title == "Do anything" }).count == 1 else { return nil }
        for child in node.children { if let found = scope(child) { return found } }
        return node
    }
    guard let chat = scope(root), !["AXWindow", "AXWebArea"].contains(chat.role),
          let anchor = submittedPromptAnchors(chat, prompt: prior.prompt).first,
          let index = chat.all.firstIndex(where: { $0.identity == anchor.identity })
    else { try fail("prior_chat_binding_missing_or_broad") }
    let after = Array(chat.all.dropFirst(index + 1))
    guard !after.contains(where: { $0.role == "AXHeading" && $0.title == "You said:" }),
          !after.contains(where: { $0.role == "AXProgressIndicator" || ($0.role == "AXButton" && ["stop", "stop generating", "cancel"].contains($0.title.lowercased())) })
    else { try fail("prior_chat_has_newer_or_running_turn") }
    let rendered = after.filter { $0.role == "AXStaticText" && $0.children.isEmpty }.map { $0.value }.joined(separator: "\n")
    let pattern = prior.endMarker.map { NSRegularExpression.escapedPattern(for: String($0)) }.joined(separator: "\n?")
    guard try NSRegularExpression(pattern: pattern).numberOfMatches(in: rendered, range: NSRange(rendered.startIndex..., in: rendered)) == 1
    else { try fail("prior_chat_end_marker_missing_or_ambiguous") }
}

// Bind the picker to the narrowest subtree containing the unique draft composer and Send.
func select(_ root: Node, prompt: String, project: String, allowMenu: Bool = false) throws -> Node {
    let all = root.all
    guard allowMenu || !all.contains(where: { $0.role == "AXMenuItem" }) else { try fail("close_existing_menus") }
    if let prior = priorTurn {
        try verifyPriorBinding(root, prior: prior)
        guard all.contains(where: { $0.title == project || ($0.role == "AXStaticText" && $0.value == project) })
        else { try fail("project_label_mismatch_or_ambiguity") }
    } else {
        guard all.filter({ $0.role == "AXPopUpButton" && $0.title == "Change project: " + project }).count == 1
        else { try fail("project_label_mismatch_or_ambiguity") }
    }
    let composers = all.filter { $0.role == "AXTextArea" && $0.title == "Do anything" }
    failureContext["verification_stage"] = "draft_binding"
    guard composers.count == 1, promptMatches(composers[0].value, expected: prompt), composers[0].enabled else {
        failureContext["draft_comparison"] = ["expected_value": prompt, "composer_count": composers.count,
            "observed_composers": composers.map { ["value": $0.value, "enabled": $0.enabled] as [String: Any] }]
        try fail("draft_mismatch_or_ambiguity")
    }
    failureContext.removeValue(forKey: "verification_stage")
    func scope(_ node: Node) -> Node? {
        let nodes = node.all
        guard nodes.contains(where: { $0.role == "AXTextArea" && $0.title == "Do anything" }),
              nodes.contains(where: { $0.role == "AXButton" && $0.title == "Send" }) else { return nil }
        for child in node.children { if let found = scope(child) { return found } }
        return node
    }
    guard let container = scope(root) else { try fail("composer_send_scope_missing") }
    guard container.role != "AXWindow",
          !container.all.contains(where: { $0.title == "Change project: " + project })
    else { try fail("composer_scope_too_broad") }
    let send = container.all.filter { $0.role == "AXButton" && $0.title == "Send" }
    guard send.count == 1, send[0].enabled else { try fail("send_not_uniquely_enabled") }
    let pickers = container.all.filter {
        $0.role == "AXPopUpButton" && ($0.title.hasPrefix("GPT-") || $0.title == "Select model" || $0.title == "Select effort")
    }
    guard pickers.count == 1, pickers[0].enabled else { try fail("picker_mismatch_or_ambiguity") }
    return pickers[0]
}

func selectModelMenu(_ root: Node, prompt: String, project: String) throws -> Node {
    _ = try select(root, prompt: prompt, project: project, allowMenu: true)
    let items = root.all.filter { $0.role == "AXMenuItem" }
    guard !items.contains(where: { $0.title.hasPrefix("GPT-") }) else { try fail("model_list_already_open") }
    let matches = items.filter { $0.title == "Select model" }
    guard matches.count == 1, matches[0].enabled else { try fail("select_model_menu_ambiguity") }
    return matches[0]
}

func selectModelItem(_ root: Node, prompt: String, project: String, model: String) throws -> Node {
    _ = try select(root, prompt: prompt, project: project, allowMenu: true)
    let items = root.all.filter { $0.role == "AXMenuItem" }
    guard !items.contains(where: { $0.title == "Select model" }) else { try fail("expected_model_list") }
    let matches = items.filter { $0.title == model }
    guard matches.count == 1, matches[0].enabled else { try fail("requested_model_missing_disabled_or_ambiguous") }
    return matches[0]
}

func selectSend(_ root: Node, prompt: String, project: String, model: String) throws -> Node {
    let picker = try select(root, prompt: prompt, project: project)
    guard picker.title.hasPrefix(model + " ") else { try fail("model_mismatch_before_send") }
    let sends = root.all.filter { $0.role == "AXButton" && $0.title == "Send" }
    guard sends.count == 1, sends[0].enabled else { try fail("send_ambiguity") }
    return sends[0]
}

func readResponse(_ root: Node, prompt: String, project: String, model: String, requestID: String) throws -> [String: Any] {
    let all = root.all
    // The draft's Change project control disappears when the chat is submitted.
    guard all.contains(where: { $0.title == project || $0.title == "Change project: " + project || ($0.role == "AXStaticText" && $0.value == project) })
    else { try fail("response_project_label_mismatch") }
    let composers = all.filter { $0.role == "AXTextArea" && $0.title == "Do anything" }
    guard composers.count == 1 else { try fail("response_composer_ambiguity") }
    let submitted = submittedPromptAnchors(root, prompt: prompt)
    guard submitted.count == 1, !promptMatches(composers[0].value, expected: prompt) else {
        return ["ok": false, "state": "uncertain", "completion_evidence_verified": false,
                "submission_evidence_verified": false, "reason": "submitted_message_not_observed"]
    }
    func scope(_ node: Node) -> Node? {
        let nodes = node.all
        guard nodes.contains(where: { $0.role == "AXTextArea" && $0.title == "Do anything" }),
              nodes.contains(where: { $0.identity == submitted[0].identity }) else { return nil }
        for child in node.children { if let found = scope(child) { return found } }
        return node
    }
    guard let chat = scope(root)
    else { try fail("response_chat_scope_missing") }
    guard !["AXWindow", "AXWebArea"].contains(chat.role) else { try fail("response_chat_scope_too_broad") }
    func modelOwner(_ node: Node) -> Node? {
        let nodes = node.all
        guard nodes.contains(where: { $0.role == "AXTextArea" && $0.title == "Do anything" }),
              nodes.contains(where: { $0.role == "AXPopUpButton" && ($0.title.hasPrefix("GPT-") || $0.title == "Select model" || $0.title == "Select effort") })
        else { return nil }
        for child in node.children { if let owner = modelOwner(child) { return owner } }
        return node
    }
    guard let owner = modelOwner(chat) else { try fail("response_model_scope_missing") }
    let models = owner.all.filter { $0.role == "AXPopUpButton" && ($0.title.hasPrefix("GPT-") || $0.title == "Select model" || $0.title == "Select effort") }
    guard models.count == 1, models[0].title.hasPrefix(model + " ") else { try fail("response_model_mismatch") }
    func content(_ node: Node) -> [Node] {
        if node.role == "AXTextArea" && node.title == "Do anything" { return [] }
        return [node] + node.children.flatMap { content($0) }
    }
    let contentNodes = content(chat)
    guard let promptIndex = contentNodes.firstIndex(where: { $0.identity == submitted[0].identity })
    else { try fail("response_prompt_scope_missing") }
    let afterNodes = contentNodes.dropFirst(promptIndex + 1)
    guard !afterNodes.contains(where: {
        ["AXTextArea", "AXTextField"].contains($0.role) && $0.title != "Do anything" && !$0.value.isEmpty
    }) else { try fail("unsupported_response_text_control") }
    let after = afterNodes.filter { $0.role == "AXStaticText" && $0.children.isEmpty }
    let announcements = after.filter { $0.value.hasPrefix("Response complete: ") }.map { $0.value }
    let texts = after.filter { !$0.value.hasPrefix("Response complete: ") }.map { $0.value }
    let nonce = requestID.replacingOccurrences(of: "-", with: "").uppercased()
    let begin = "BEGIN_CODEX_RESPONSE_" + nonce
    let end = "END_CODEX_RESPONSE_" + nonce
    let rendered = texts.joined(separator: "\n")
    func markerRanges(_ marker: String) throws -> [NSRange] {
        let pattern = marker.map { NSRegularExpression.escapedPattern(for: String($0)) }.joined(separator: "\n?")
        return try NSRegularExpression(pattern: pattern).matches(in: rendered, range: NSRange(rendered.startIndex..., in: rendered)).map { $0.range }
    }
    let beginnings = try markerRanges(begin)
    let endings = try markerRanges(end)
    var result: [String: Any] = ["ok": false, "state": "running",
        "submission_evidence_verified": true, "completion_evidence_verified": false,
        "verified_model_label": models[0].title, "workspace_check": "visible_project_label_only",
        "response_format": "rendered_text_envelope"]
    if beginnings.count > 1 || endings.count > 1 || announcements.count > 1 { try fail("duplicate_response_envelope") }
    guard beginnings.count == 1, endings.count == 1,
          let startRange = Range(beginnings[0], in: rendered),
          let endRange = Range(endings[0], in: rendered), startRange.upperBound <= endRange.lowerBound
    else {
        result["reason"] = "response_envelope_incomplete"
        return result
    }
    let busy = chat.all.contains { $0.role == "AXProgressIndicator" ||
        ($0.role == "AXButton" && ["stop", "stop generating", "stop response", "cancel"].contains($0.title.lowercased())) }
    if busy { result["reason"] = "turn_still_running"; return result }
    // The live announcement is transient. Finished-answer controls after this
    // request's END marker plus an idle composer provide durable evidence.
    var offset = 0
    var endLeafIndex: Int? = nil
    let ordered = Array(afterNodes)
    for (index, node) in ordered.enumerated() {
        if node.role == "AXStaticText" && node.children.isEmpty && !node.value.hasPrefix("Response complete: ") {
            offset += (node.value as NSString).length
            if offset >= NSMaxRange(endings[0]) { endLeafIndex = index; break }
            offset += 1
        }
    }
    let tail = endLeafIndex.map { Array(ordered.dropFirst($0 + 1)) } ?? []
    let actionTitles = tail.filter { $0.role == "AXButton" && $0.enabled }.map { $0.title }
    let durable = composers[0].enabled && ["Copy", "Rate response", "Fork chat from here"].allSatisfy {
        title in actionTitles.filter { $0 == title }.count == 1
    }
    guard !announcements.isEmpty || durable else { result["reason"] = "completion_marker_missing"; return result }
    result["completion_method"] = announcements.isEmpty ? "final_response_actions_and_idle_composer" : "live_announcement"
    guard ["", "Do anything"].contains(composers[0].value.trimmingCharacters(in: .whitespacesAndNewlines))
    else { try fail("response_composer_not_cleared") }
    result["response_text"] = String(rendered[startRange.upperBound..<endRange.lowerBound]).trimmingCharacters(in: .newlines)
    if let announcement = announcements.last { result["completion_marker_text"] = announcement }
    result["completion_evidence_verified"] = true
    result["state"] = "completed"
    result["ok"] = true
    return result
}

func claimSend(_ claim: URL, expectedResponse: String) throws {
    try FileManager.default.createDirectory(at: claim.deletingLastPathComponent(), withIntermediateDirectories: true,
                                          attributes: [.posixPermissions: 0o700])
    let record: [String: Any] = ["state": "uncertain", "expected_response": expectedResponse,
                               "claimed_at": ISO8601DateFormatter().string(from: Date())]
    let bytes = try JSONSerialization.data(withJSONObject: record, options: [.sortedKeys, .prettyPrinted])
    let descriptor = Darwin.open(claim.path, O_CREAT | O_EXCL | O_WRONLY, mode_t(0o600))
    guard descriptor >= 0 else { try fail("send_claim_creation_failed_no_retry") }
    let written = bytes.withUnsafeBytes { buffer in Darwin.write(descriptor, buffer.baseAddress, buffer.count) }
    let syncResult = Darwin.fsync(descriptor)
    Darwin.close(descriptor)
    guard written == bytes.count && syncResult == 0 else { try fail("send_claim_write_failed_no_retry") }
    // Sync the containing directory before dispatching the irreversible click.
    let directoryFD = Darwin.open(claim.deletingLastPathComponent().path, O_RDONLY)
    guard directoryFD >= 0 else { try fail("send_claim_directory_open_failed") }
    let directorySync = Darwin.fsync(directoryFD)
    Darwin.close(directoryFD)
    guard directorySync == 0 else { try fail("send_claim_directory_sync_failed") }
}

func saveObservation(_ root: Node, taskPath: String) throws {
    func encode(_ node: Node) -> [String: Any] {
        ["role": node.role, "title": node.title, "value": node.value, "enabled": node.enabled,
         "value_truncated": false, "actions": node.actions, "children": node.children.map(encode)]
    }
    let snapshot: [String: Any] = ["ok": true, "read_only": true, "truncated": false,
        "incomplete": false, "unreadable_elements": 0, "values_truncated": false, "windows": [encode(root)]]
    let data = try JSONSerialization.data(withJSONObject: snapshot, options: [.sortedKeys, .prettyPrinted])
    let path = URL(fileURLWithPath: taskPath).deletingLastPathComponent().appendingPathComponent("response-snapshot.json")
    try data.write(to: path, options: .atomic)
    try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: path.path)
}

func emit(_ result: [String: Any], code: Int32 = 0) -> Never {
    if let data = try? JSONSerialization.data(withJSONObject: result, options: [.sortedKeys, .prettyPrinted]),
       let output = String(data: data, encoding: .utf8) { print(output) }
    exit(code)
}

func selfTest() throws {
    func node(_ role: String, _ title: String = "", _ value: String = "", _ children: [Node] = []) -> Node {
        Node(element: nil, role: role, title: title, value: value, enabled: true, actions: [], children: children)
    }
    let composer = node("AXTextArea", "Do anything", "test")
    let picker = node("AXPopUpButton", "GPT-5.6 Sol Medium")
    let send = node("AXButton", "Send")
    let project = node("AXPopUpButton", "Change project: harness")
    let good = node("AXWindow", "", "", [project, node("AXGroup", "", "", [composer, picker, send])])
    guard try select(good, prompt: "test", project: "harness").title == picker.title else { try fail("self_test_selection") }
    let cases: [(Node, String, String)] = [
        (good, "wrong", "harness"), (good, "test", "wrong"),
        (node("AXWindow", "", "", [good, composer]), "test", "harness"),
        (node("AXWindow", "", "", [good, node("AXMenuItem", "Select model")]), "test", "harness"),
        (node("AXWindow", "", "", [project, composer, node("AXGroup", "", "", [picker, send])]), "test", "harness"),
        (node("AXWindow", "", "", [project, composer, picker, picker, send]), "test", "harness")
    ]
    for (tree, prompt, workspace) in cases {
        do { _ = try select(tree, prompt: prompt, project: workspace) }
        catch is ProbeFailure { continue }
        try fail("self_test_expected_rejection")
    }
    let fixtureData = try Data(contentsOf: URL(fileURLWithPath: "tests/fixtures/rendered-draft.json"))
    let fixture = try JSONSerialization.jsonObject(with: fixtureData) as! [String: String]
    let expectedDraft = fixture["expected"]!, observedDraft = fixture["observed"]!
    guard promptMatches(observedDraft, expected: expectedDraft) else { try fail("rendered_draft_regression") }
    for edited in [observedDraft.replacingOccurrences(of: "40 customers", with: "400 customers"),
                   observedDraft.replacingOccurrences(of: "BEGIN_CODEX_RESPONSE_", with: "BAD_CODEX_RESPONSE_"),
                   String(observedDraft.dropLast()), observedDraft + "extra"] {
        guard !promptMatches(edited, expected: expectedDraft) else { try fail("edited_rendered_draft_accepted") }
    }
    for sensitive in ["```\n- code\n\n```", "line\n    - indented\n\nnext", "line\n\t- tabbed", "line  \n\nnext", "line\n   \nnext"] {
        let altered = sensitive.components(separatedBy: "\n").filter { !$0.isEmpty }.map {
            $0.hasPrefix("- ") ? "• " + $0.dropFirst(2) : $0
        }.joined(separator: "\n")
        if altered != sensitive {
            guard !promptMatches(altered, expected: sensitive) else { try fail("sensitive_text_normalized") }
        }
    }
    let renderedComposer = node("AXTextArea", "Do anything", observedDraft)
    let renderedGroup = node("AXGroup", "", "", [project, node("AXGroup", "", "", [renderedComposer, picker, send])])
    guard try selectSend(renderedGroup, prompt: expectedDraft, project: "harness", model: "GPT-5.6 Sol").title == "Send"
    else { try fail("rendered_send_binding") }
    for bad in [node("AXGroup", "", "", [renderedGroup, renderedComposer]),
                node("AXGroup", "", "", [node("AXPopUpButton", "Change project: other"), node("AXGroup", "", "", [renderedComposer, picker, send])])] {
        do { _ = try select(bad, prompt: expectedDraft, project: "harness"); try fail("rendered_ambiguous_binding_accepted") }
        catch let error as ProbeFailure { guard error.message != "rendered_ambiguous_binding_accepted" else { throw error } }
    }
    let model = node("AXMenuItem", "GPT-5.6 Sol")
    let other = node("AXMenuItem", "GPT-5.6 Terra")
    for items in [[model, other], [other, model]] {
        let list = node("AXGroup", "", "", [good] + items)
        guard try selectModelItem(list, prompt: "test", project: "harness", model: model.title).title == model.title
        else { try fail("model_order_test") }
    }
    for items in [[other], [model, model]] {
        do { _ = try selectModelItem(node("AXGroup", "", "", [good] + items), prompt: "test", project: "harness", model: model.title) }
        catch is ProbeFailure { continue }
        try fail("model_identity_expected_rejection")
    }
    guard try selectSend(good, prompt: "test", project: "harness", model: "GPT-5.6 Sol").title == "Send"
    else { try fail("send_selector_test") }
    do { _ = try selectSend(good, prompt: "test", project: "harness", model: "GPT-6.1 Sol"); try fail("send_model_test_unexpected_success") }
    catch let error as ProbeFailure { guard error.message == "model_mismatch_before_send" else { throw error } }
    let directory = FileManager.default.temporaryDirectory.appendingPathComponent("codex-harness-claim-test-" + UUID().uuidString)
    defer { try? FileManager.default.removeItem(at: directory) }
    let claim = directory.appendingPathComponent("claim.json")
    try claimSend(claim, expectedResponse: "TEST")
    let original = try Data(contentsOf: claim)
    do { try claimSend(claim, expectedResponse: "OTHER"); try fail("duplicate_claim_unexpected_success") }
    catch let error as ProbeFailure { guard error.message == "send_claim_creation_failed_no_retry" else { throw error } }
    guard try Data(contentsOf: claim) == original else { try fail("duplicate_claim_modified_record") }
    guard !spatialRoles("AXMenuItem").contains("AXTextArea"), spatialRoles("AXMenuItem").contains("AXMenuItem"),
          spatialRoles("AXButton").contains("AXTextArea") else { try fail("menu_layer_test") }
    let requestID = "00000000-0000-4000-8000-000000000001"
    let begin = "BEGIN_CODEX_RESPONSE_00000000000040008000000000000001"
    let end = "END_CODEX_RESPONSE_00000000000040008000000000000001"
    func responseTree(_ leaves: [String], completed: Bool = true, submittedPrompt: String = "generic prompt") -> Node {
        let messages = [node("AXStaticText", "", submittedPrompt)] + leaves.map { node("AXStaticText", "", $0) }
        let announcement = completed ? [node("AXStaticText", "", "Response complete: answer")] : []
        let compose = node("AXGroup", "", "", [node("AXTextArea", "Do anything", "Do anything\n"), picker])
        return node("AXWindow", "", "", [node("AXButton", "harness"), node("AXGroup", "", "", messages + announcement + [compose])])
    }
    let response = try readResponse(responseTree([String(begin.prefix(21)), String(begin.dropFirst(21)), "Paragraph", "    code", end]),
                                    prompt: "generic prompt", project: "harness", model: "GPT-5.6 Sol", requestID: requestID)
    guard response["response_text"] as? String == "Paragraph\n    code", response["completion_evidence_verified"] as? Bool == true
    else { try fail("generic_response_reader_test") }
    let renderedResponse = try readResponse(responseTree([begin, "answer", end], submittedPrompt: observedDraft),
                                            prompt: expectedDraft, project: "harness", model: "GPT-5.6 Sol", requestID: requestID)
    guard renderedResponse["completion_evidence_verified"] as? Bool == true else { try fail("rendered_response_attribution") }
    let renderedPrior = PriorTurn(prompt: expectedDraft, endMarker: end)
    try verifyPriorBinding(responseTree([begin, "answer", end], submittedPrompt: observedDraft), prior: renderedPrior)
    let waiting = try readResponse(responseTree([begin, "answer", end], completed: false), prompt: "generic prompt",
                                   project: "harness", model: "GPT-5.6 Sol", requestID: requestID)
    guard waiting["completion_evidence_verified"] as? Bool == false else { try fail("generic_early_completion_test") }
    let durableActions = ["Copy", "Rate response", "Fork chat from here"].map { node("AXButton", $0) }
    let idleCompose = node("AXGroup", "", "", [node("AXTextArea", "Do anything", "Do anything\n"), picker])
    func durableTree(_ busy: Bool, _ actionsFirst: Bool = false) -> Node {
        let answer = [node("AXStaticText", "", "generic prompt")] + [begin, "answer", end].map { node("AXStaticText", "", $0) }
        let contents = actionsFirst ? durableActions + answer : answer + durableActions
        return node("AXWindow", "", "", [node("AXButton", "harness"), node("AXGroup", "", "",
            contents + (busy ? [node("AXButton", "Stop")] : []) + [idleCompose])])
    }
    let durableResponse = try readResponse(durableTree(false), prompt: "generic prompt", project: "harness", model: "GPT-5.6 Sol", requestID: requestID)
    guard durableResponse["completion_evidence_verified"] as? Bool == true,
          durableResponse["completion_method"] as? String == "final_response_actions_and_idle_composer"
    else { try fail("durable_response_test") }
    for tree in [durableTree(true), durableTree(false, true)] {
        let refused = try readResponse(tree, prompt: "generic prompt", project: "harness", model: "GPT-5.6 Sol", requestID: requestID)
        guard refused["completion_evidence_verified"] as? Bool == false else { try fail("durable_response_early_test") }
    }
    do { _ = try readResponse(responseTree([begin, "answer", end, begin]), prompt: "generic prompt",
                             project: "harness", model: "GPT-5.6 Sol", requestID: requestID); try fail("generic_duplicate_marker_test") }
    catch let error as ProbeFailure { guard error.message == "duplicate_response_envelope" else { throw error } }
    let prior = PriorTurn(prompt: "previous prompt", endMarker: end)
    let followupCompose = node("AXGroup", "", "", [node("AXTextArea", "Do anything", "follow-up"), picker, send])
    func followupTree(_ extra: [Node] = []) -> Node {
        node("AXWindow", "", "", [node("AXButton", "harness"), node("AXGroup", "", "",
            [node("AXStaticText", "", "previous prompt"), node("AXStaticText", "", end)] + extra + [followupCompose])])
    }
    try verifyPriorBinding(followupTree(), prior: prior)
    priorTurn = prior
    guard try select(followupTree(), prompt: "follow-up", project: "harness").title == picker.title
    else { try fail("followup_selection_test") }
    priorTurn = nil
    for bad in [followupTree([node("AXHeading", "You said:")]),
                followupTree([node("AXButton", "Stop")]),
                followupTree([node("AXStaticText", "", end)])] {
        do { try verifyPriorBinding(bad, prior: prior); try fail("followup_bad_binding_accepted") }
        catch let error as ProbeFailure { guard error.message != "followup_bad_binding_accepted" else { throw error } }
    }
    let splitSnapshot = try JSONSerialization.jsonObject(with: Data(contentsOf: URL(fileURLWithPath: "tests/fixtures/split-prompt-response.json"))) as! [String: Any]
    let splitTask = try JSONSerialization.jsonObject(with: Data(contentsOf: URL(fileURLWithPath: "tests/fixtures/split-prompt-task.json"))) as! [String: Any]
    func convert(_ object: [String: Any]) -> Node {
        Node(element: nil, role: object["role"] as? String ?? "", title: object["title"] as? String ?? "",
             value: object["value"] as? String ?? "", enabled: object["enabled"] as? Bool ?? false,
             actions: object["actions"] as? [String] ?? [], children: (object["children"] as? [[String: Any]] ?? []).map(convert))
    }
    let splitRoot = convert((splitSnapshot["windows"] as! [[String: Any]])[0])
    let splitReply = try readResponse(splitRoot, prompt: splitTask["prompt"] as! String,
                                     project: "codex-desktop-harness", model: "GPT-5.6 Sol", requestID: splitTask["request_id"] as! String)
    for edited in [(splitTask["prompt"] as! String).replacingOccurrences(of: "40 customers", with: "400 customers"),
                   (splitTask["prompt"] as! String).replacingOccurrences(of: "BEGIN_CODEX_RESPONSE_", with: "BAD_CODEX_RESPONSE_")] {
        let rejected = try readResponse(splitRoot, prompt: edited, project: "codex-desktop-harness", model: "GPT-5.6 Sol", requestID: splitTask["request_id"] as! String)
        guard rejected["completion_evidence_verified"] as? Bool != true else { try fail("split_prompt_edit_accepted") }
    }
    try verifyPriorBinding(splitRoot, prior: PriorTurn(prompt: splitTask["prompt"] as! String,
                           endMarker: "END_CODEX_RESPONSE_9759783725CD40CB8FB4C8672D9CF843"))
    guard splitReply["completion_evidence_verified"] as? Bool == true,
          (splitReply["response_text"] as? String)?.contains("08:40–08:45") == true else { try fail("split_prompt_response_regression") }
    emit(["ok": true, "self_test": true, "rejection_cases": cases.count + 4,
          "model_order_cases": 2, "claim_io_test": true, "response_reader_cases": 6, "followup_binding_cases": 5, "desktop_accessed": false])
}

do {
    var args = Array(CommandLine.arguments.dropFirst())
    let spatialOnly = args.contains("--spatial-only")
    args.removeAll { $0 == "--spatial-only" }
    let dryRun = args.last == "--dry-run"
    if dryRun { args.removeLast() }
    if args == ["--self-test"] { try selfTest() }
    if (args.count == 4 || (args.count == 5 && args[4] == "--model-list") || (args.count == 6 && args[4] == "--select-model")) && args[0] == "--check-snapshot" && args[2] == "--task" {
        func load(_ path: String) throws -> [String: Any] {
            guard let object = try JSONSerialization.jsonObject(with: Data(contentsOf: URL(fileURLWithPath: path))) as? [String: Any]
            else { try fail("invalid_json") }
            return object
        }
        let saved = try load(args[1])
        let task = try load(args[3])
        guard saved["ok"] as? Bool == true, saved["incomplete"] as? Bool == false,
              let windows = saved["windows"] as? [[String: Any]], windows.count == 1,
              let prompt = task["prompt"] as? String, let workspace = task["workspace"] as? String
        else { try fail("incomplete_snapshot_or_task") }
        func convert(_ object: [String: Any]) -> Node {
            Node(element: nil, role: object["role"] as? String ?? "",
                 title: object["title"] as? String ?? "", value: object["value"] as? String ?? "",
                 enabled: object["enabled"] as? Bool ?? false, actions: object["actions"] as? [String] ?? [],
                 children: (object["children"] as? [[String: Any]] ?? []).map(convert))
        }
        let root = convert(windows[0])
        let project = URL(fileURLWithPath: workspace).lastPathComponent
        let picker: Node
        if args.count == 6 { picker = try selectModelItem(root, prompt: prompt, project: project, model: args[5]) }
        else if args.count == 5 { picker = try selectModelMenu(root, prompt: prompt, project: project) }
        else { picker = try select(root, prompt: prompt, project: project) }
        emit(["ok": true, "picker_title": picker.title, "desktop_accessed": false, "action_attempted": false])
    }
    guard (args.count == 3 && ["press", "show-menu", "click", "model-list"].contains(args[2]))
          || (args.count == 4 && ["select-model", "send-test", "send-request", "read-request", "prepare-followup", "capture-focus", "restore-focus"].contains(args[2]) && args[3].hasPrefix("GPT-")),
          args[0] == "--task" else {
        try fail("usage: ax-picker-probe --task work/task.json press|show-menu|click|model-list [--dry-run], or select-model 'GPT-5.6 Sol' [--dry-run], or --self-test")
    }
    let data = try Data(contentsOf: URL(fileURLWithPath: args[1]))
    guard let task = try JSONSerialization.jsonObject(with: data) as? [String: Any],
          let prompt = task["prompt"] as? String, !prompt.isEmpty,
          let workspace = task["workspace"] as? String, workspace.hasPrefix("/"),
          FileManager.default.fileExists(atPath: workspace) else { try fail("invalid_task") }
    if ["capture-focus", "restore-focus"].contains(args[2]) {
        let focusURL = URL(fileURLWithPath: args[1]).deletingLastPathComponent().appendingPathComponent("caller-focus.json")
        if args[2] == "capture-focus" {
            guard let caller = NSWorkspace.shared.frontmostApplication, let bundle = caller.bundleIdentifier,
                  bundle != "com.openai.codex" else { try fail("caller_focus_not_external") }
            let record: [String: Any] = ["pid": caller.processIdentifier, "bundle": bundle]
            try JSONSerialization.data(withJSONObject: record).write(to: focusURL, options: .atomic)
            try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: focusURL.path)
            emit(["ok": true, "action_attempted": false])
        }
        guard !dryRun else { emit(["ok": true, "action_attempted": false]) }
        guard let record = try JSONSerialization.jsonObject(with: Data(contentsOf: focusURL)) as? [String: Any],
              let pid = record["pid"] as? Int32, let bundle = record["bundle"] as? String,
              let caller = NSRunningApplication(processIdentifier: pid), caller.bundleIdentifier == bundle,
              bundle != "com.openai.codex", caller.activate(options: []) else { try fail("caller_focus_restore_failed") }
        emit(["ok": true, "action_attempted": true])
    }
    let previous = task["previous_turn"] as? [String: Any]
    if let previous = previous {
        guard args.count >= 4, let priorPrompt = previous["prompt"] as? String, !priorPrompt.isEmpty,
              let priorID = previous["request_id"] as? String, let priorUUID = UUID(uuidString: priorID),
              previous["workspace"] as? String == workspace,
              previous["desktop_model"] as? String == args[3] else { try fail("invalid_previous_turn") }
        priorTurn = PriorTurn(prompt: priorPrompt, endMarker: "END_CODEX_RESPONSE_" + priorUUID.uuidString.replacingOccurrences(of: "-", with: ""))
    }
    guard AXIsProcessTrusted() else { try fail("accessibility_not_granted") }
    let apps = NSRunningApplication.runningApplications(withBundleIdentifier: "com.openai.codex")
    guard apps.count == 1, let app = apps.first else { try fail("application_ambiguity") }
    let autoFocus = task["auto_focus"] as? Bool == true && ["select-model", "prepare-followup"].contains(args[2]) && !dryRun
    if autoFocus {
        // Only the initial draft-selection step acquires focus. Subsequent click
        // checks still abort if the user changes apps; reads never steal focus.
        guard !app.isHidden || app.unhide() else { try fail("target_app_unhide_failed") }
        if NSWorkspace.shared.frontmostApplication?.processIdentifier != app.processIdentifier {
            guard app.activate(options: []) else { try fail("target_app_activation_failed") }
        }
        let focusDeadline = Date().addingTimeInterval(5)
        while NSWorkspace.shared.frontmostApplication?.processIdentifier != app.processIdentifier && Date() < focusDeadline {
            // Allow Cocoa activation notifications to be processed while waiting.
            RunLoop.current.run(until: Date().addingTimeInterval(0.1))
        }
        guard NSWorkspace.shared.frontmostApplication?.processIdentifier == app.processIdentifier
        else {
            failureContext["observed_foreground_bundle"] = NSWorkspace.shared.frontmostApplication?.bundleIdentifier ?? "unknown"
            try fail("target_app_activation_not_observed")
        }
    }
    func tree() throws -> Node {
        guard NSWorkspace.shared.frontmostApplication?.processIdentifier == app.processIdentifier
        else { try fail("target_app_must_be_frontmost") }
        let application = AXUIElementCreateApplication(app.processIdentifier)
        guard let windows = attribute(application, kAXWindowsAttribute) as? [AXUIElement], windows.count == 1
        else { try fail("expected_one_app_window") }
        var budget = 4000
        return try read(windows[0], budget: &budget)
    }
    let project = URL(fileURLWithPath: workspace).lastPathComponent
    if args[2] == "prepare-followup" {
        guard let previous = previous, let prior = priorTurn,
              let priorID = previous["request_id"] as? String,
              let expected = previous["response_text"] as? String, !expected.isEmpty else { try fail("previous_completed_turn_required") }
        let observed = try tree()
        try verifyPriorBinding(observed, prior: prior)
        let response = try readResponse(observed, prompt: prior.prompt, project: project, model: args[3], requestID: priorID)
        guard response["completion_evidence_verified"] as? Bool == true, response["response_text"] as? String == expected
        else { try fail("previous_response_mismatch") }
        let composers = observed.all.filter { $0.role == "AXTextArea" && $0.title == "Do anything" }
        guard composers.count == 1, let composer = composers[0].element, composers[0].enabled else { try fail("followup_composer_ambiguity") }
        if dryRun { emit(["ok": true, "dry_run": true, "action_attempted": false, "prior_chat_binding_verified": true]) }
        guard NSWorkspace.shared.frontmostApplication?.processIdentifier == app.processIdentifier,
              AXUIElementSetAttributeValue(composer, kAXValueAttribute as CFString, prompt as CFString) == .success
        else { try fail("followup_composer_write_failed") }
        let deadline = Date().addingTimeInterval(5)
        repeat {
            let fresh = try tree()
            if (try? select(fresh, prompt: prompt, project: project)) != nil {
                emit(["ok": true, "action_attempted": true, "submission_attempted": false, "prior_chat_binding_verified": true, "draft_verified": true])
            }
            Thread.sleep(forTimeInterval: 0.1)
        } while Date() < deadline
        try fail("followup_draft_verification_failed")
    }
    let sendTest = args[2] == "send-test"
    let generalRequest = ["send-request", "read-request"].contains(args[2])
    let sending = sendTest || args[2] == "send-request"
    var expectedResponse = ""
    var claimURL: URL?
    var identity: [String: Any] = [:]
    if sending || generalRequest {
        guard let requestID = task["request_id"] as? String, let uuid = UUID(uuidString: requestID)
        else { try fail("send_test_requires_uuid") }
        expectedResponse = "DESKTOP_SPIKE_" + uuid.uuidString.replacingOccurrences(of: "-", with: "")
        guard !sendTest || prompt == "Reply with exactly " + expectedResponse + ". Do not use tools or change any files."
        else { try fail("send_test_only_accepts_nonce_bound_harmless_prompt") }
        let directory = URL(fileURLWithPath: args[1]).deletingLastPathComponent().appendingPathComponent("send-claims")
        claimURL = directory.appendingPathComponent(uuid.uuidString.lowercased() + ".json")
        if sending { guard !FileManager.default.fileExists(atPath: claimURL!.path) else { try fail("send_already_claimed_no_retry") } }
        if generalRequest {
            guard let attemptID = task["attempt_id"] as? String, UUID(uuidString: attemptID) != nil
            else { try fail("general_request_requires_attempt_id") }
            identity = ["request_id": uuid.uuidString.lowercased(), "attempt_id": attemptID,
                        "workspace": workspace,
                        "wire_prompt_sha256": SHA256.hash(data: Data(prompt.utf8)).map { String(format: "%02x", $0) }.joined()]
            if args[2] == "read-request" {
                guard FileManager.default.fileExists(atPath: claimURL!.path) else { try fail("read_request_requires_prior_send_claim") }
                failureContext = identity
                failureContext["submission_attempted"] = true
                let observed = try tree()
                try saveObservation(observed, taskPath: args[1])
                var result = try readResponse(observed, prompt: prompt, project: project, model: args[3], requestID: requestID)
                result.merge(identity) { _, new in new }
                result["submission_attempted"] = true
                emit(result, code: result["ok"] as? Bool == true ? 0 : 6)
            }
        }
    }
    func resolveInitial() throws -> Node {
        let root = try tree()
        return sending ? try selectSend(root, prompt: prompt, project: project, model: args[3])
            : try select(root, prompt: prompt, project: project)
    }
    func initialTree() throws -> Node {
        if !autoFocus { return try tree() }
        // Deep-link handling may finish after application activation. Observe
        // until the exact prompt/project/composer is ready, without clicking.
        let deadline = Date().addingTimeInterval(10)
        var lastError: Error = ProbeFailure(message: "draft_not_ready")
        repeat {
            guard NSWorkspace.shared.frontmostApplication?.processIdentifier == app.processIdentifier
            else { try fail("focus_changed_while_waiting_for_draft") }
            do {
                let observed = try tree()
                _ = try select(observed, prompt: prompt, project: project)
                return observed
            } catch { lastError = error }
            Thread.sleep(forTimeInterval: 0.1)
        } while Date() < deadline
        throw lastError
    }
    let before = try initialTree()
    let picker = sending ? try selectSend(before, prompt: prompt, project: project, model: args[3])
        : try select(before, prompt: prompt, project: project)
    let action = ["click", "model-list", "select-model", "send-test", "send-request"].contains(args[2]) ? "mouse_click" : (args[2] == "press" ? kAXPressAction : kAXShowMenuAction)
    var result: [String: Any] = ["ok": true, "picker_title": picker.title,
        "advertised_actions": picker.actions, "requested_action": action,
        "action_attempted": false, "submission_attempted": false,
        "workspace_check": "visible_project_label_only", "dry_run": dryRun,
        "spatial_only": spatialOnly]
    if args[2] == "select-model" { result["requested_model"] = args[3] }
    result.merge(identity) { _, new in new }
    failureContext = result
    if sending {
        result["requested_model"] = args[3]
        if sendTest { result["expected_response"] = expectedResponse }
    }
    if dryRun { emit(result) }
    if args[2] == "select-model" && picker.title.hasPrefix(args[3] + " ") {
        let verified = try select(try tree(), prompt: prompt, project: project)
        guard verified.title.hasPrefix(args[3] + " ") else { try fail("selected_model_changed") }
        result["verified_model_label"] = verified.title
        result["model_verified_with_closed_picker"] = true
        result["model_already_selected"] = true
        emit(result)
    }
    // Re-read and revalidate immediately before the one allowed action.
    let freshPicker = try resolveInitial()
    guard let original = picker.element, let fresh = freshPicker.element,
          CFEqual(original, fresh), freshPicker.title == picker.title else { try fail("picker_changed") }
    func bounds(_ target: AXUIElement, limitSize: Bool = true) throws -> CGRect {
        guard let position = attribute(target, kAXPositionAttribute),
              let size = attribute(target, kAXSizeAttribute),
              CFGetTypeID(position) == AXValueGetTypeID(), CFGetTypeID(size) == AXValueGetTypeID()
        else { try fail("picker_bounds_unavailable") }
        var origin = CGPoint.zero
        var extent = CGSize.zero
        guard AXValueGetValue(position as! AXValue, .cgPoint, &origin),
              AXValueGetValue(size as! AXValue, .cgSize, &extent),
              origin.x.isFinite, origin.y.isFinite, extent.width.isFinite, extent.height.isFinite,
              extent.width > 0, extent.height > 0,
              (!limitSize || (extent.width <= 800 && extent.height <= 200))
        else { try fail("invalid_picker_bounds") }
        return CGRect(origin: origin, size: extent)
    }
    func click(_ resolve: () throws -> Node) throws -> [String: CGFloat] {
        let started = Date()
        let deadline = started.addingTimeInterval(4)
        var lastRect: CGRect?
        var stableSince = Date()
        var lastElement: AXUIElement?
        var selected: Node?
        var lastReadError = ""
        repeat {
            do {
                let node = try resolve()
                guard let element = node.element else { try fail("missing_native_target") }
                let rect = try bounds(element)
                if rect != lastRect || lastElement == nil || !CFEqual(element, lastElement!) {
                    stableSince = Date()
                    lastRect = rect
                    lastElement = element
                }
                if Date().timeIntervalSince(started) >= 0.8 && Date().timeIntervalSince(stableSince) >= 0.6 {
                    selected = node
                    break
                }
            } catch {
                stableSince = Date()
                lastRect = nil
                lastElement = nil
                lastReadError = String(describing: error)
            }
            Thread.sleep(forTimeInterval: 0.1)
        } while Date() < deadline
        guard let node = selected, let target = node.element, let stableRect = lastRect
        else { try fail("target_did_not_settle: " + lastReadError) }
        let freshNode = try resolve()
        guard let fresh = freshNode.element, CFEqual(target, fresh), try bounds(fresh) == stableRect
        else { try fail("target_moved_before_click") }
        let center = CGPoint(x: stableRect.midX, y: stableRect.midY)
        var displayCount: UInt32 = 0
        guard CGGetDisplaysWithPoint(center, 0, nil, &displayCount) == .success, displayCount > 0
        else { try fail("picker_center_offscreen") }
        guard let down = CGEvent(mouseEventSource: nil, mouseType: .leftMouseDown, mouseCursorPosition: center, mouseButton: .left),
              let up = CGEvent(mouseEventSource: nil, mouseType: .leftMouseUp, mouseCursorPosition: center, mouseButton: .left)
        else { try fail("mouse_event_creation_failed") }
        guard NSWorkspace.shared.frontmostApplication?.processIdentifier == app.processIdentifier
        else { try fail("focus_changed_before_click") }
        let application = AXUIElementCreateApplication(app.processIdentifier)
        var hit: AXUIElement?
        let hitError = AXUIElementCopyElementAtPosition(application, Float(center.x), Float(center.y), &hit)
        guard hitError == .success, let hitElement = hit else { try fail("hit_test_unavailable") }
        var ancestor: AXUIElement? = hitElement
        var matched = false
        for _ in 0..<16 {
            guard let element = ancestor else { break }
            if CFEqual(element, fresh) { matched = true; break }
            ancestor = attribute(element, kAXParentAttribute) as! AXUIElement?
        }
        var matchMethod = "target_or_descendant"
        var nativeHitMatched = matched
        if !matched && string(hitElement, kAXRoleAttribute) == "AXGroup" {
            let root = try tree()
            let hitNodes = root.all.filter { node in
                guard let element = node.element else { return false }
                return CFEqual(element, hitElement)
            }
            let containsTarget = hitNodes.count == 1 && hitNodes[0].all.contains { node in
                guard let element = node.element else { return false }
                return CFEqual(element, fresh)
            }
            let roles = spatialRoles(freshNode.role)
            var candidates: [Node] = []
            for candidate in root.all where roles.contains(candidate.role) && candidate.enabled {
                guard let element = candidate.element else { continue }
                // An unreadable clickable rectangle makes this spatial check uncertain.
                let rect = try bounds(element, limitSize: false)
                if rect.contains(center) { candidates.append(candidate) }
            }
            let soleTarget = candidates.count == 1 && candidates[0].element != nil && CFEqual(candidates[0].element!, fresh)
            nativeHitMatched = containsTarget && soleTarget
            matched = nativeHitMatched || (spatialOnly && soleTarget)
            if nativeHitMatched { matchMethod = "ancestor_group_and_unique_control_at_point" }
            else if matched { matchMethod = "unique_control_at_point_coarse_native_hit_untrusted" }
            result["group_hit_check"] = ["contains_target": containsTarget,
                                          "controls_at_point": candidates.map { ["role": $0.role, "title": $0.title] }]
        }
        failureContext = result
        failureContext["hit_role"] = string(hitElement, kAXRoleAttribute)
        failureContext["hit_title"] = string(hitElement, kAXTitleAttribute)
        failureContext["intended_target_title"] = freshNode.title
        guard matched else {
            try fail("hit_test_wrong_target: " + string(hitElement, kAXRoleAttribute) + " / " + string(hitElement, kAXTitleAttribute))
        }
        var checks = result["click_checks"] as? [[String: Any]] ?? []
        checks.append(["title": freshNode.title, "hit_test_matched": nativeHitMatched, "click_allowed": true,
                       "hit_role": string(hitElement, kAXRoleAttribute), "hit_match_method": matchMethod,
                       "settle_seconds": Date().timeIntervalSince(started),
                       "x": center.x, "y": center.y])
        result["click_checks"] = checks
        if sending {
            guard let claim = claimURL else { try fail("missing_send_claim") }
            try claimSend(claim, expectedResponse: expectedResponse)
            result["claim_file"] = claim.path
            failureContext = result
            let finalNode = try resolve()
            guard let finalElement = finalNode.element, CFEqual(finalElement, fresh),
                  try bounds(finalElement) == stableRect,
                  NSWorkspace.shared.frontmostApplication?.processIdentifier == app.processIdentifier
            else { try fail("send_target_changed_after_claim_no_retry") }
            result["submission_attempted"] = true
            failureContext = result
        }
        down.post(tap: .cghidEventTap)
        up.post(tap: .cghidEventTap)
        return ["x": center.x, "y": center.y]
    }
    if ["click", "model-list", "select-model", "send-test", "send-request"].contains(args[2]) {
        result["click_center"] = try click { try resolveInitial() }
        result["action_attempted"] = true
        result["mouse_events_posted"] = true
    } else {
        let outcome = AXUIElementPerformAction(fresh, action as CFString)
        result["action_attempted"] = true
        result["ax_error_code"] = outcome.rawValue
        result["action_returned_success"] = outcome == .success
    }
    if args[2] == "send-request" {
        let deadline = Date().addingTimeInterval(60)
        var lastError = ""
        repeat {
            do {
                let observed = try tree()
                try saveObservation(observed, taskPath: args[1])
                let response = try readResponse(observed, prompt: prompt, project: project, model: args[3], requestID: task["request_id"] as! String)
                result.merge(response) { _, new in new }
                if response["completion_evidence_verified"] as? Bool == true || response["submission_evidence_verified"] as? Bool == true { break }
            } catch { lastError = String(describing: error) }
            Thread.sleep(forTimeInterval: 0.25)
        } while Date() < deadline
        if result["completion_evidence_verified"] as? Bool != true { result["ok"] = false }
        if !lastError.isEmpty { result["last_observation_error"] = lastError }
        if let claim = claimURL {
            let bytes = try JSONSerialization.data(withJSONObject: result, options: [.prettyPrinted, .sortedKeys])
            try bytes.write(to: claim, options: .atomic)
            try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: claim.path)
        }
        emit(result, code: result["ok"] as? Bool == true ? 0 : 6)
    }
    if sendTest {
        let deadline = Date().addingTimeInterval(60)
        var verified = false
        var lastError = ""
        repeat {
            do {
                let root = try tree()
                let texts = root.all.filter { $0.role == "AXStaticText" }.map { $0.value }
                let composer = root.all.filter { $0.role == "AXTextArea" && $0.title == "Do anything" }
                let models = root.all.filter { $0.role == "AXPopUpButton" && $0.title.hasPrefix(args[3] + " ") }
                if texts.filter({ promptMatches($0, expected: prompt) }).count == 1,
                   texts.filter({ $0 == expectedResponse }).count == 1,
                   texts.filter({ $0 == "Response complete: " + expectedResponse }).count == 1,
                   composer.count == 1, !promptMatches(composer[0].value, expected: prompt), models.count == 1 {
                    result["verified_model_label"] = models[0].title
                    // Return the observed AX text, not a copy of the expected token.
                    result["response_text"] = texts.first { $0 == expectedResponse }
                    result["completion_marker_text"] = texts.first { $0 == "Response complete: " + expectedResponse }
                    verified = true
                    break
                }
            } catch { lastError = String(describing: error) }
            Thread.sleep(forTimeInterval: 0.25)
        } while Date() < deadline
        result["ok"] = verified
        result["completion_evidence_verified"] = verified
        result["state"] = verified ? "completed_test" : "uncertain"
        if !lastError.isEmpty { result["last_observation_error"] = lastError }
        if let claim = claimURL {
            let bytes = try JSONSerialization.data(withJSONObject: result, options: [.prettyPrinted, .sortedKeys])
            try bytes.write(to: claim, options: .atomic)
            try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: claim.path)
        }
        emit(result, code: verified ? 0 : 6)
    }
    // A return code is not evidence of a menu transition. Observe for up to three seconds.
    let deadline = Date().addingTimeInterval(3)
    var observed = false
    var lastError = ""
    repeat {
        do {
            let items = try tree().all.filter { $0.role == "AXMenuItem" }.map { $0.title }
            if items.contains("Select model") {
                result["observed_menu_items"] = items
                observed = true
                break
            }
        } catch { lastError = String(describing: error) }
        Thread.sleep(forTimeInterval: 0.15)
    } while Date() < deadline
    result["menu_open_observed"] = observed
    if observed && ["model-list", "select-model"].contains(args[2]) {
      do {
        let selected = try selectModelMenu(try tree(), prompt: prompt, project: project)
        let validated = try selectModelMenu(try tree(), prompt: prompt, project: project)
        guard let old = selected.element, let target = validated.element, CFEqual(old, target)
        else { try fail("menu_item_changed") }
        result["model_list_click_center"] = try click { try selectModelMenu(try tree(), prompt: prompt, project: project) }
        result["model_list_action_attempted"] = true
        let listDeadline = Date().addingTimeInterval(3)
        var listObserved = false
        repeat {
            do {
                let items = try tree().all.filter { $0.role == "AXMenuItem" }.map { $0.title }
                if items.contains(where: { $0.hasPrefix("GPT-") }) && !items.contains("Select model") {
                    result["observed_model_items"] = items
                    listObserved = true
                    break
                }
            } catch { lastError = String(describing: error) }
            Thread.sleep(forTimeInterval: 0.15)
        } while Date() < listDeadline
        result["model_list_open_observed"] = listObserved
        observed = listObserved
      } catch {
        result["model_list_error"] = String(describing: error)
        observed = false
      }
    }
    if observed && args[2] == "select-model" {
      do {
        let model = args[3]
        let selected = try selectModelItem(try tree(), prompt: prompt, project: project, model: model)
        let validated = try selectModelItem(try tree(), prompt: prompt, project: project, model: model)
        guard let old = selected.element, let target = validated.element, CFEqual(old, target)
        else { try fail("model_item_changed") }
        result["model_click_center"] = try click { try selectModelItem(try tree(), prompt: prompt, project: project, model: model) }
        result["model_action_attempted"] = true
        let deadline = Date().addingTimeInterval(3)
        var evidence = false
        repeat {
            do {
                let root = try tree()
                let picker = try select(root, prompt: prompt, project: project, allowMenu: true)
                let announcements = root.all.filter { $0.role == "AXStaticText" }.map { $0.value }
                result["last_observed_picker_title"] = picker.title
                result["last_model_announcements"] = announcements.filter { $0.hasPrefix("GPT-") && $0.contains(" of ") }
                let listStillOpen = root.all.contains { $0.role == "AXMenuItem" && $0.title.hasPrefix("GPT-") }
                if !listStillOpen && (picker.title.hasPrefix(model + " ") || announcements.contains(where: { $0.hasPrefix(model + " ") && $0.contains(" of ") })) {
                    evidence = true
                    break
                }
            } catch { lastError = String(describing: error) }
            Thread.sleep(forTimeInterval: 0.15)
        } while Date() < deadline
        result["model_selection_evidence_observed"] = evidence
        guard evidence else { try fail("model_selection_not_observed") }
        // Dismiss with Escape rather than clicking through a changing menu.
        let root = try tree()
        if root.all.contains(where: { $0.role == "AXMenuItem" }) {
            _ = try select(try tree(), prompt: prompt, project: project, allowMenu: true)
            guard NSWorkspace.shared.frontmostApplication?.processIdentifier == app.processIdentifier,
                  let down = CGEvent(keyboardEventSource: nil, virtualKey: 53, keyDown: true),
                  let up = CGEvent(keyboardEventSource: nil, virtualKey: 53, keyDown: false)
            else { try fail("escape_event_unavailable_or_focus_changed") }
            down.post(tap: .cghidEventTap)
            up.post(tap: .cghidEventTap)
            result["close_picker_action_attempted"] = true
            result["close_picker_action"] = "Escape"
        }
        let closeDeadline = Date().addingTimeInterval(3)
        var verified = false
        repeat {
            do {
                let picker = try select(try tree(), prompt: prompt, project: project)
                if picker.title.hasPrefix(model + " ") {
                    result["verified_model_label"] = picker.title
                    verified = true
                    break
                }
            } catch { lastError = String(describing: error) }
            Thread.sleep(forTimeInterval: 0.15)
        } while Date() < closeDeadline
        result["model_verified_with_closed_picker"] = verified
        observed = verified
      } catch {
        result["model_selection_error"] = String(describing: error)
        observed = false
      }
    }
    result["ok"] = observed
    if !lastError.isEmpty { result["last_observation_error"] = lastError }
    emit(result, code: observed ? 0 : 6)
} catch {
    failureContext["ok"] = false
    failureContext["error"] = String(describing: error)
    if failureContext["submission_attempted"] == nil { failureContext["submission_attempted"] = false }
    emit(failureContext, code: 2)
}
