// 小删输入法 — 薄壳 IME
// 职责：接收本地端口(51967)的 JSON 行指令，把文字以"预编辑(带下划线)"形式
//       实时画进当前输入框 / 定稿上屏。语音识别由 Python 引擎完成。
// 指令：{"op":"marked","text":"..."} 预编辑   {"op":"commit","text":"..."} 定稿
//       {"op":"clear"} 清空预编辑
import Cocoa
import InputMethodKit

let kPort: UInt16 = 51967

class XiaoShanController: IMKInputController {
    static weak var active: XiaoShanController?

    override func activateServer(_ sender: Any!) {
        super.activateServer(sender)
        XiaoShanController.active = self
    }

    override func deactivateServer(_ sender: Any!) {
        if XiaoShanController.active === self {
            XiaoShanController.active = nil
        }
        super.deactivateServer(sender)
    }

    override func handle(_ event: NSEvent!, client sender: Any!) -> Bool {
        return false   // 不拦截按键；口述期间用户不打字
    }
}

func withActiveClient(_ body: (IMKTextInput) -> Void) {
    DispatchQueue.main.async {
        if let c = XiaoShanController.active, let client = c.client() {
            body(client.takeUnretainedValue())
        }
    }
}

func applyMarked(_ text: String) {
    withActiveClient { client in
        let range = NSRange(location: (text as NSString).length, length: 0)
        client.setMarkedText(text, selectionRange: range,
                             replacementRange: NSRange(location: NSNotFound, length: NSNotFound))
    }
}

func applyCommit(_ text: String) {
    withActiveClient { client in
        client.setMarkedText("", selectionRange: NSRange(location: 0, length: 0),
                             replacementRange: NSRange(location: NSNotFound, length: NSNotFound))
        client.insertText(text, replacementRange: NSRange(location: NSNotFound, length: NSNotFound))
    }
}

func applyClear() {
    withActiveClient { client in
        client.setMarkedText("", selectionRange: NSRange(location: 0, length: 0),
                             replacementRange: NSRange(location: NSNotFound, length: NSNotFound))
    }
}

// ---------- 本地socket服务：收 JSON 行 ----------
func startSocket() {
    Thread.detachNewThread {
        let fd = socket(AF_INET, SOCK_STREAM, 0)
        guard fd >= 0 else { return }
        var one: Int32 = 1
        setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &one, socklen_t(MemoryLayout<Int32>.size))
        var addr = sockaddr_in()
        addr.sin_family = sa_family_t(AF_INET)
        addr.sin_port = kPort.bigEndian
        addr.sin_addr = in_addr(s_addr: inet_addr("127.0.0.1"))
        let bindOk = withUnsafePointer(to: &addr) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                bind(fd, $0, socklen_t(MemoryLayout<sockaddr_in>.size))
            }
        }
        guard bindOk == 0, listen(fd, 4) == 0 else { close(fd); return }
        while true {
            let cfd = accept(fd, nil, nil)
            guard cfd >= 0 else { continue }
            Thread.detachNewThread {
                defer { close(cfd) }
                var buf = Data()
                var chunk = [UInt8](repeating: 0, count: 65536)
                while true {
                    let n = read(cfd, &chunk, chunk.count)
                    if n <= 0 { break }
                    buf.append(contentsOf: chunk[0..<n])
                    while let idx = buf.firstIndex(of: UInt8(ascii: "\n")) {
                        let lineData = buf[0..<idx]
                        buf.removeSubrange(0...idx)
                        if let line = String(data: Data(lineData), encoding: .utf8),
                           let obj = try? JSONSerialization.jsonObject(with: Data(line.utf8)) as? [String: Any],
                           let op = obj["op"] as? String {
                            let text = obj["text"] as? String ?? ""
                            switch op {
                            case "marked": applyMarked(text)
                            case "commit": applyCommit(text)
                            case "clear": applyClear()
                            default: break
                            }
                        }
                    }
                }
            }
        }
    }
}

// ---------- 启动 ----------
let connectionName = "XiaoShan_IME_Connection"
guard let server = IMKServer(name: connectionName,
                             bundleIdentifier: Bundle.main.bundleIdentifier) else {
    exit(1)
}
startSocket()
NSApplication.shared.run()
