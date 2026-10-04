# MaintenanceAI user guide

MaintenanceAI fills in maintenance reports starting from a description written in your
own words. The artificial intelligence runs **on your PC**: no data is sent to the
Internet. Every report is always **checked and approved by you** before it is exported.

![Home](img/home.png)

## 1. Getting started

1. **Install** the app with `MaintenanceAI-Setup.exe`: no administrator rights needed.
   A *MaintenanceAI* shortcut appears on the Desktop.
2. On first launch a short wizard asks for the language and the data folder.
3. **Install the AI engine** (only once, ~2 GB): click *AI not installed* at the top
   right, or let the app do it if you chose a model in the installer. From then on the
   AI also works without Internet.
4. Follow the **guided tour** of the main features (replay it from
   *Settings → Help and support*).

> Without the AI the app still works: the draft fields are filled in manually during review.

## 2. Modules

A **module** is the report template: a Word (DOCX) or Excel (XLSX) file of yours where
the parts to fill in are written as `{{field_name}}`, for example
`Job date: {{job_date}}`.

- **New module** (sidebar or `Ctrl+N`): choose *From my own file* and select the
  DOCX/XLSX. Fields and mapping are created automatically.
- **Template editor** (*Module* tab): select text in the document preview and turn it
  into a field, without opening Word or writing JSON.
- **Reference documents**: procedures, checklists, manuals (PDF and scans too) in the
  module's *Reference documents* folder. The AI uses them as instructions, never as
  proof of work done.
- **Module AI rules**: permanent instructions. The AI reads them but cannot change them.

## 3. Creating a report

1. Select the module in the sidebar and open the **Report** tab.
2. Describe the job: date, plant, machine, components, activities, outcome, technician.
   The more details, the more fields are filled in. You can also:
   - **add photos** (or open the Windows *Camera*): they are included in the PDF;
   - switch to **From documents** to fill in from job sheets, checklists or scans.
3. Press **Generate draft with AI** (`Ctrl+E`). The phases (Context → AI → Source check →
   Review → Export) are shown below the button; *Show the AI output in real time* displays
   the text while it is generated.

## 4. Review and approval

![Side-by-side review](img/revisione.png)

The review shows **the sources on the left** (your description and documents) and
**the fields on the right**. Clicking a field highlights its value in the sources.

- **Found in the sources**: the value appears in the description or documents.
- **To check** (red): numbers, codes, dates or names that do **not** appear in the
  sources — likely invented by the AI. Always check them.
- **Inferred**: chosen from a list or yes/no, not verifiable word by word.
- **Missing**: empty field or `NON_SPECIFICATO`.

On long texts **Improve text** rewrites the sentence in technical form without adding
facts (you can undo). The draft is **saved automatically** every 20 seconds: if you
close, you find it in *Home → Drafts to complete*.

**Approve and generate the report** produces a PDF (with photos), your template filled in
(DOCX/XLSX) and the approved data (JSON, the official source). From the final window you
can open the **PDF preview**, print or prepare an **email**.

## 5. History

- **Global search** (`Ctrl+F`) in report descriptions and data.
- **Filters** by status, module, period (*dd/mm/yyyy*), technician and plant/department/machine.
- **Actions** (also with right click): PDF preview, open/edit, **duplicate**, **versions**,
  folder, delete.
- **Export to Excel**: summary of the filtered reports. **Import CSV/Excel**: each row
  becomes a report.
- **Versions**: every approval or later change saves a version that can be compared and restored.

## 6. AI documents

Create documents, edit documents (new version), audit documents, fill in a module from
documents, extract text from scans (Windows OCR), AI rules. Originals are never changed.

## 7. Settings

- **Appearance**: light, dark or *like Windows* theme; language; **text size** (80–160%).
- **Artificial intelligence**: profile, **GPU acceleration** (Vulkan), preload at startup,
  turn off when idle, CPU threads, context, **semantic search**, source check.
- **Data and backup**: data folder (also **on the network**, with a lock against
  simultaneous use), **backup** to a ZIP file, **restore**, automatic backup.
- **Help and support**: this guide, guided tour, **diagnostic package**, **report a problem**.

## 8. Keyboard shortcuts

| Keys | Action |
|---|---|
| `Ctrl+1` … `Ctrl+6` | Home, Report, History, Module, AI documents, Settings |
| `Ctrl+Tab` / `Ctrl+Shift+Tab` | Next / previous tab |
| `Ctrl+N` | New module |
| `Ctrl+E` | Generate the report draft |
| `Ctrl+F` | Search the history |
| `Ctrl+B` | Show/hide the sidebar |
| `Ctrl+,` | Settings |
| `F1` | Guide |
| `F5` | Reload modules |
| `Esc` | Close the dialog |
| `Del` | Delete the selected reports (History) |

## 9. FAQ

**Does the AI invent data?** Built-in rules forbid inventing dates, names, codes and
numbers, and the *source check* highlights in red the values not found in the sources.
The light model (0.6B) makes more mistakes: with at least 6 GB of RAM use the 1.7B.

**Is Internet required?** Only to download the AI components once.

**The AI is slow.** Use the *compatibility* profile, enable the GPU if available, close
programs that use a lot of RAM.

**Where is my data?** In `%LOCALAPPDATA%\MaintenanceAI` (or the folder chosen in
*Settings → Data*). Make regular **backups**; the automatic one is weekly.

**Windows shows "Windows protected your PC".** The installer is not digitally signed:
click *More info → Run anyway*.
