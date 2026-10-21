"use strict";

const copyButton = document.querySelector("#copy-commands");
const commands = document.querySelector("#setup-commands");
const copyStatus = document.querySelector("#copy-status");

if (copyButton && commands && copyStatus && navigator.clipboard?.writeText) {
  copyButton.hidden = false;
  copyButton.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(commands.textContent.trim());
      copyStatus.textContent = "Commands copied. Read the guide before running them.";
    } catch {
      copyStatus.textContent = "Copy was blocked by your browser. Select the commands above to copy them manually.";
      const selection = window.getSelection();
      if (selection) {
        const range = document.createRange();
        range.selectNodeContents(commands);
        selection.removeAllRanges();
        selection.addRange(range);
      }
    }
  });
}
