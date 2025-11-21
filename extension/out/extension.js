"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.activate = activate;
exports.deactivate = deactivate;
const vscode = require("vscode");
const node_fetch_1 = require("node-fetch");
function cleanGeneratedCode(code) {
    // Remove ```python or ``` at the start/end of the code block
    return code.replace(/^```(?:python)?\s*/, '').replace(/```$/, '').trim();
}
function activate(context) {
    const COMMENT_TRIGGER = /(?:#|\/\/)\s*generate\s+(.*)/i;
    const processedLines = new Set();
    const disposable = vscode.workspace.onDidChangeTextDocument(async (event) => {
        const editor = vscode.window.activeTextEditor;
        if (!editor || editor.document !== event.document)
            return;
        for (const change of event.contentChanges) {
            // Only trigger on Enter (new line)
            if (!change.text.includes('\n'))
                continue;
            const lineIndex = change.range.start.line;
            const lineText = editor.document.lineAt(lineIndex).text;
            if (processedLines.has(lineText))
                continue; // Skip if already processed
            const match = lineText.match(COMMENT_TRIGGER);
            if (!match)
                continue;
            const query = match[1].trim();
            if (!query)
                continue;
            processedLines.add(lineText); // Mark line as processed
            vscode.window.showInformationMessage(`💡 Generating code for: "${query}"`);
            try {
                const workspaceFolder = vscode.workspace.getWorkspaceFolder(editor.document.uri);
                const parent_root = workspaceFolder?.uri.fsPath || '';
                const res = await (0, node_fetch_1.default)('http://127.0.0.1:8000/chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ question: query, parent_root }),
                });
                if (!res.ok)
                    throw new Error(`Server returned ${res.status}: ${res.statusText}`);
                const data = await res.json();
                const generatedCode = cleanGeneratedCode(data.answer);
                // Show webview preview
                const panel = vscode.window.createWebviewPanel('coderagCodePreview', 'Generated Code Preview', vscode.ViewColumn.Beside, { enableScripts: true });
                panel.webview.html = getCodeWebviewContent(generatedCode);
                panel.webview.onDidReceiveMessage(async (msg) => {
                    if (msg.command === 'accept') {
                        await editor.edit(editBuilder => {
                            editBuilder.insert(new vscode.Position(lineIndex + 1, 0), `${generatedCode}\n`);
                        });
                        panel.dispose();
                        vscode.window.showInformationMessage('✅ Code inserted!');
                    }
                    else if (msg.command === 'reject') {
                        panel.dispose();
                        vscode.window.showInformationMessage('❌ Code generation rejected');
                    }
                });
            }
            catch (err) {
                vscode.window.showErrorMessage(`❌ Code generation failed: ${err.message}`);
                processedLines.delete(lineText); // Allow retry if failed
            }
        }
    });
    context.subscriptions.push(disposable);
}
function deactivate() { }
function getCodeWebviewContent(code) {
    return /*html*/ `
  <!DOCTYPE html>
  <html lang="en">
  <head>
    <meta charset="UTF-8">
    <style>
      body { font-family: "Segoe UI", sans-serif; padding: 15px; background: #1e1e1e; color: #d4d4d4; }
      pre { background: #252526; padding: 15px; border-radius: 8px; overflow-x: auto; max-height: 80vh; white-space: pre-wrap; }
      button { margin: 10px 5px 0 0; padding: 8px 16px; border: none; border-radius: 5px; cursor: pointer; font-weight: bold; }
      #accept { background: #007acc; color: white; }
      #reject { background: #c33; color: white; }
      button:hover { opacity: 0.9; }
    </style>
  </head>
  <body>
    <h3>Generated Code Preview</h3>
    <pre><code>${code.replace(/</g, '&lt;').replace(/>/g, '&gt;')}</code></pre>
    <button id="accept">Accept</button>
    <button id="reject">Reject</button>

    <script>
      const vscode = acquireVsCodeApi();
      document.getElementById('accept').addEventListener('click', () => vscode.postMessage({ command: 'accept' }));
      document.getElementById('reject').addEventListener('click', () => vscode.postMessage({ command: 'reject' }));
    </script>
  </body>
  </html>
  `;
}
//# sourceMappingURL=extension.js.map