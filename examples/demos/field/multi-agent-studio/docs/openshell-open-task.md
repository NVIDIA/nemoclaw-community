# OpenShell in Open Task

Use **OpenShell in action** to show how a presenter can grant one protected agent access to a source during a task.

1. In **Open Task**, select **OpenShell in action** and send the goal. The example selects **Hired + Standby** and asks for Shell by name. Casey assigns Shell to read the linked NVIDIA article and a Coding agent to build a webpage from Shell’s brief.
2. Shell tries only that article. If it can read the article, it saves the brief and the team can proceed. If the read fails, Shell stops browsing. When OpenShell records a denial and Casey confirms the missing article is needed, an amber **!** appears in **Mission Control**. An ordinary connection error alone does not trigger a permission request.
3. In **Mission Control**, open **OpenShell Policy** for Shell. To allow the read, approve the article’s website. To keep it blocked, leave the policy as it is. Close the panel to return to Mission Control, then select **Continue**.
4. With new access to the site, Shell retries the same article. Without new access, it uses the evidence it already has and identifies what is missing. The Coding agent uses that brief for the webpage. **Continue** resumes the task without granting any permissions itself.

## Present the approval step again

If Shell already has access to the site, the example can finish without asking for approval. Use **Reset Open Task** to clear the last task and revoke Shell’s saved website approvals before the next run. Hired agents keep their personal policies when you reset Open Task.

The same review flow applies to protected hired agents. For open-ended research they can try other permitted sources within the assignment before Casey asks for access. Approvals apply to the selected agent. While Mission Control waits for your decision, the execution clock pauses. After 15 minutes the task continues with the evidence it has.
