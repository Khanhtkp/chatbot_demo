"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.activate = activate;
exports.deactivate = deactivate;
const vscode = require("vscode");
const node_fetch_1 = require("node-fetch");
function activate(context) {
    // File watcher to notify backend about new files
    const watcher = vscode.workspace.createFileSystemWatcher('**/*.{ts,js,py,java,cpp,cs,txt, ipynb}');
    watcher.onDidCreate(async (uri) => {
        console.log('🟢 New file detected:', uri.fsPath);
        try {
            const workspaceFolder = vscode.workspace.getWorkspaceFolder(uri);
            if (!workspaceFolder)
                return;
            await (0, node_fetch_1.default)('http://127.0.0.1:8000/index', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ parent_root: workspaceFolder.uri.fsPath }),
            });
            console.log('✅ Backend indexed new file');
        }
        catch (err) {
            console.error('❌ Indexing failed:', err);
        }
    });
    context.subscriptions.push(watcher);
    const disposable = vscode.commands.registerCommand('coderag.chat', async () => {
        const panel = vscode.window.createWebviewPanel('coderagChat', 'CodeRAG Chat', vscode.ViewColumn.Beside, { enableScripts: true });
        panel.webview.html = getWebviewContent();
        panel.webview.onDidReceiveMessage(async (msg) => {
            console.log('📩 Received from WebView:', msg);
            if (!msg.question)
                return;
            let parent = '';
            try {
                const active = vscode.window.activeTextEditor;
                if (active && active.document && !active.document.isUntitled) {
                    const workspaceFolder = vscode.workspace.getWorkspaceFolder(active.document.uri);
                    parent = workspaceFolder?.uri.fsPath || '';
                }
                else if (vscode.workspace.workspaceFolders && vscode.workspace.workspaceFolders.length > 0) {
                    parent = vscode.workspace.workspaceFolders[0].uri.fsPath;
                }
                if (!parent) {
                    panel.webview.postMessage({ id: msg.id, answer: '⚠️ No file or workspace detected.' });
                    return;
                }
            }
            catch (err) {
                console.error('Editor detection failed:', err);
                panel.webview.postMessage({ id: msg.id, answer: '⚠️ Could not detect active file or workspace.' });
                return;
            }
            console.log('🟡 Sending to backend:', { question: msg.question, parent });
            try {
                // Auto-index parent folder before sending the question
                await (0, node_fetch_1.default)('http://127.0.0.1:8000/index', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ parent_root: parent }),
                });
                const res = await (0, node_fetch_1.default)('http://127.0.0.1:8000/chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ question: msg.question, parent_root: parent }),
                });
                if (!res.ok)
                    throw new Error(`Server returned ${res.status}: ${res.statusText}`);
                const data = (await res.json());
                console.log('✅ Server response JSON:', data);
                panel.webview.postMessage({ id: msg.id, answer: data.answer });
            }
            catch (err) {
                console.error('❌ Fetch failed:', err);
                panel.webview.postMessage({ id: msg.id, answer: `❌ Error: ${err.message}` });
            }
        });
    });
    context.subscriptions.push(disposable);
}
function deactivate() { }
/**
 * HTML + JS for CodeRAG Chat
 */
function getWebviewContent() {
    return /*html*/ `
  <!DOCTYPE html>
  <html lang="en">
  <head>
    <meta charset="UTF-8">
    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
    <style>
      body {
        font-family: "Segoe UI", sans-serif;
        padding: 15px;
        background-color: #1e1e1e;
        color: #d4d4d4;
      }
      textarea {
        width: 100%;
        height: 80px;
        resize: vertical;
        font-family: monospace;
        border-radius: 8px;
        border: 1px solid #3c3c3c;
        background: #252526;
        color: #fff;
        padding: 8px;
        box-sizing: border-box;
      }
      button {
        margin-top: 10px;
        padding: 8px 14px;
        border: none;
        border-radius: 5px;
        background-color: #007acc;
        color: white;
        cursor: pointer;
      }
      button:hover {
        background-color: #005fa3;
      }
      #ans {
        background: #252526;
        padding: 12px;
        border-radius: 6px;
        margin-top: 16px;
        font-size: 14px;
        line-height: 1.5;
        max-height: 65vh;
        overflow-y: auto;
      }
      .message {
        margin-bottom: 16px;
        padding-bottom: 8px;
        border-bottom: 1px solid #3c3c3c;
      }
      .user {
        color: #9cdcfe;
        margin-bottom: 6px;
      }
      .assistant {
        border-left: 3px solid #007acc;
        padding-left: 10px;
        margin-top: 6px;
      }
      pre code {
        display: block;
        padding: 10px;
        background: #1e1e1e;
        border-radius: 8px;
        overflow-x: auto;
      }
      code {
        background: #333;
        color: #dcdcaa;
        padding: 3px 6px;
        border-radius: 4px;
      }
      .cursor {
        display: inline-block;
        width: 6px;
        background: #007acc;
        animation: blink 1s steps(1) infinite;
      }
      @keyframes blink {
        50% { background: transparent; }
      }
    </style>
  </head>

  <body>
    <h2>💬 CodeRAG Chat</h2>
    <textarea id="q" placeholder="Ask something about your code..."></textarea>
    <button id="ask">Ask</button>
    <div id="ans"></div>

    <script>
      const vscode = acquireVsCodeApi();
      const ansBox = document.getElementById('ans');

      document.getElementById('ask').addEventListener('click', () => {
        const q = document.getElementById('q').value.trim();
        if (!q) return;

        const msgId = Date.now();
        appendMessage(q, msgId);
        vscode.postMessage({ question: q, id: msgId });
        document.getElementById('q').value = "";
      });

      window.addEventListener('message', event => {
        const { id, answer } = event.data;
        const replyDiv = document.querySelector(\`#reply-\${id}\`);
        if (!replyDiv) return;

        replyDiv.innerHTML = "";
        typeWriterEffect(marked.parse(answer), replyDiv);
      });

      function appendMessage(question, id) {
        const wrapper = document.createElement('div');
        wrapper.className = 'message';
        wrapper.innerHTML = \`
          <div class='user'><strong>You:</strong> \${question}</div>
          <div class='assistant'><strong>Assistant:</strong><br><em id='reply-\${id}'>Thinking...</em></div>
        \`;
        ansBox.appendChild(wrapper);
        ansBox.scrollTop = ansBox.scrollHeight;
      }

      function typeWriterEffect(fullHTML, container) {
        const tempDiv = document.createElement('div');
        tempDiv.innerHTML = fullHTML;
        const text = tempDiv.innerText;
        container.innerHTML = "";
        let i = 0;

        function type() {
          if (i < text.length) {
            container.textContent += text.charAt(i);
            i++;
            setTimeout(type, 15);
          } else {
            container.innerHTML = fullHTML;
          }
        }
        type();
      }
    </script>
  </body>
  </html>`;
}
//# sourceMappingURL=extension.js.map