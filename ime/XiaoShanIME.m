// 小删输入法 — 薄壳 IME（Objective-C）
// 职责：接收本地端口(51967)的 JSON 行指令，把文字以"预编辑(带下划线)"形式
//       实时画进当前输入框 / 定稿上屏。语音识别由 Python 引擎完成。
// 指令：{"op":"marked","text":"..."} 预编辑   {"op":"commit","text":"..."} 定稿
//       {"op":"clear"} 清空预编辑
#import <Cocoa/Cocoa.h>
#import <InputMethodKit/InputMethodKit.h>
#import <sys/socket.h>
#import <netinet/in.h>
#import <unistd.h>
#import <pthread.h>

static IMKInputController *gActive = nil;

@interface XiaoShanController : IMKInputController
@end

@implementation XiaoShanController
- (void)activateServer:(id)sender {
    [super activateServer:sender];
    gActive = self;
}
- (void)deactivateServer:(id)sender {
    if (gActive == self) gActive = nil;
    [super deactivateServer:sender];
}
// 不拦截按键；口述期间用户不打字
- (BOOL)handle:(NSEvent *)event client:(id)sender {
    return NO;
}
@end

static void applyOp(NSString *op, NSString *text) {
    dispatch_async(dispatch_get_main_queue(), ^{
        if (!gActive) return;
        id<IMKTextInput> client = [gActive client];
        if (!client) return;
        NSRange unknown = NSMakeRange(NSNotFound, NSNotFound);
        if ([op isEqualToString:@"marked"]) {
            NSRange sel = NSMakeRange(text.length, 0);
            [client setMarkedText:text selectionRange:sel replacementRange:unknown];
        } else if ([op isEqualToString:@"commit"]) {
            [client setMarkedText:@"" selectionRange:NSMakeRange(0, 0) replacementRange:unknown];
            [client insertText:text replacementRange:unknown];
        } else if ([op isEqualToString:@"clear"]) {
            [client setMarkedText:@"" selectionRange:NSMakeRange(0, 0) replacementRange:unknown];
        }
    });
}

static void serveClient(int cfd) {
    NSMutableData *buf = [NSMutableData data];
    char chunk[65536];
    NSData *nlData = [@"\n" dataUsingEncoding:NSUTF8StringEncoding];
    while (1) {
        ssize_t n = read(cfd, chunk, sizeof(chunk));
        if (n <= 0) break;
        [buf appendBytes:chunk length:(NSUInteger)n];
        NSRange nl;
        while ((nl = [buf rangeOfData:nlData options:0
                                range:NSMakeRange(0, buf.length)]).location != NSNotFound) {
            NSData *lineData = [buf subdataWithRange:NSMakeRange(0, nl.location)];
            [buf replaceBytesInRange:NSMakeRange(0, nl.location + 1) withBytes:NULL length:0];
            NSString *line = [[NSString alloc] initWithData:lineData encoding:NSUTF8StringEncoding];
            if (!line) continue;
            id obj = [NSJSONSerialization JSONObjectWithData:[line dataUsingEncoding:NSUTF8StringEncoding]
                                                    options:0 error:NULL];
            if (![obj isKindOfClass:[NSDictionary class]]) continue;
            NSString *op = obj[@"op"];
            NSString *text = obj[@"text"] ?: @"";
            if (op) applyOp(op, text);
        }
    }
    close(cfd);
}

static void *socketThread(void *arg) {
    int fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) return NULL;
    int one = 1;
    setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one));
    struct sockaddr_in addr;
    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_port = htons(51967);
    addr.sin_addr.s_addr = inet_addr("127.0.0.1");
    if (bind(fd, (struct sockaddr *)&addr, sizeof(addr)) < 0) { close(fd); return NULL; }
    if (listen(fd, 4) < 0) { close(fd); return NULL; }
    while (1) {
        int cfd = accept(fd, NULL, NULL);
        if (cfd < 0) continue;
        dispatch_async(dispatch_get_global_queue(0, 0), ^{
            serveClient(cfd);
        });
    }
    return NULL;
}

int main(int argc, char *argv[]) {
    @autoreleasepool {
        IMKServer *server = [[IMKServer alloc]
            initWithName:@"XiaoShan_IME_Connection"
            bundleIdentifier:[NSBundle mainBundle].bundleIdentifier];
        if (!server) return 1;
        pthread_t t;
        pthread_create(&t, NULL, socketThread, NULL);
        [[NSApplication sharedApplication] run];
    }
    return 0;
}
