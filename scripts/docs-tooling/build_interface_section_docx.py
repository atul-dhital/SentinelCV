from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt, RGBColor


# Script lives in scripts/docs-tooling/; repo root is two levels up.
REPO_ROOT = Path(__file__).resolve().parents[2]
OUT = REPO_ROOT / "SentinelCV_Section_4_4_Interface_Design.docx"
IMG_DIR = REPO_ROOT / "page_screenshots"


def fmt_run(run, size=11, bold=False, italic=False, color="000000", font="Calibri"):
    run.font.name = font
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.italic = italic
    run.font.color.rgb = RGBColor.from_string(color)


def add_title(doc, text):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(6)
    r = p.add_run(text)
    fmt_run(r, size=16, bold=True, color="2F5496")
    return p


def add_heading(doc, text, size=13):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(10)
    p.paragraph_format.space_after = Pt(4)
    r = p.add_run(text)
    fmt_run(r, size=size, bold=True, color="2F5496")
    return p


def add_para(doc, text):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(6)
    p.paragraph_format.line_spacing = 1.15
    r = p.add_run(text)
    fmt_run(r, size=11)
    return p


def add_figure(doc, fig_no, title, image_name, note=None):
    cap = doc.add_paragraph()
    cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
    cap.paragraph_format.space_before = Pt(4)
    cap.paragraph_format.space_after = Pt(3)
    r = cap.add_run(f"Figure {fig_no}: {title}")
    fmt_run(r, size=11, bold=True)

    img_path = IMG_DIR / image_name
    pic_p = doc.add_paragraph()
    pic_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    pic_p.paragraph_format.space_before = Pt(0)
    pic_p.paragraph_format.space_after = Pt(8)
    pic_p.add_run().add_picture(str(img_path), width=Inches(6.2))

    if note:
        np = doc.add_paragraph()
        np.paragraph_format.space_before = Pt(0)
        np.paragraph_format.space_after = Pt(10)
        np.paragraph_format.line_spacing = 1.1
        nr = np.add_run(f"Note: {note}")
        fmt_run(nr, size=10.5, italic=False, color="555555")


doc = Document()
sec = doc.sections[0]
sec.top_margin = Inches(1)
sec.bottom_margin = Inches(1)
sec.left_margin = Inches(1)
sec.right_margin = Inches(1)

styles = doc.styles
styles["Normal"].font.name = "Calibri"
styles["Normal"].font.size = Pt(11)

add_title(doc, "4.4 Interface Design")
add_para(
    doc,
    "Interface design is the process of creating user-friendly screens that allow users to interact with the system easily and effectively. In the Automated Visitor Tracking and Identification System, the interface is designed for administrators, security personnel, and IT administrators. The main goal of the interface is to provide simple navigation, real-time visibility, and quick access to visitor logs and unknown visitor records.",
)
add_para(
    doc,
    "The dashboard interface allows users to monitor live camera feeds, view visitor statistics, check recent logs, and receive alerts about unknown visitors. The visitor management page allows administrators to add, update, and delete visitor profiles. The unknown visitor review page allows users to compare captured face images, check confidence scores, and assign unknown visitors to existing profiles. The reports page provides filtered logs based on date, camera, visitor name, and identification status.",
)
add_para(
    doc,
    "The interface follows a responsive design so that users can access the system from desktops, tablets, or mobile devices. This is important because security personnel may need to monitor visitor activity while moving around the facility.",
)

add_heading(doc, "4.4.1 Wireframes")
wireframes = [
    (27, "Wireframe of Login Page", "01-login.png"),
    (28, "Wireframe of Dashboard Page", "02-home.png"),
    (29, "Wireframe of Live Camera Monitoring Page", "07-live-activities.png"),
    (30, "Wireframe of Visitor Management Page", "03-visitors.png"),
    (31, "Wireframe of Unknown Visitor Review Page", "04-logs.png"),
    (32, "Wireframe of Visitor Logs and Reports Page", "05-reports.png"),
]
for fig_no, title, image in wireframes:
    add_figure(doc, fig_no, title, image)

add_heading(doc, "4.4.2 UI Screenshots")
screenshots = [
    (33, "Home Page of the System", "02-home.png",
     "The home page provides an overview of the Automated Visitor Tracking and Identification System. It introduces the main features of the system such as real-time visitor detection, face recognition, automatic visitor logs, unknown visitor alerts, and dashboard monitoring. It also provides navigation options for login and system access."),
    (34, "Login Page of the System", "01-login.png",
     "The login page allows registered users to securely access the system using their email and password. The system validates the entered credentials and redirects users to the dashboard based on their role. If the credentials are incorrect, a clear error message is displayed."),
    (35, "Dashboard Page of the System", "02-home.png",
     "The dashboard page provides a quick overview of visitor activity. It displays total visitors, known visitors, unknown visitors, active cameras, and recent alerts. It also provides navigation to live monitoring, visitor management, unknown visitor review, and reports."),
    (36, "Live Camera Monitoring Page", "07-live-activities.png",
     "The live monitoring page displays real-time camera feeds from different locations. The AI system detects and tracks visitors in the camera feed and displays labels such as track ID, known visitor name, unknown status, and confidence score. This allows security personnel to monitor visitor activity in real time."),
    (37, "Visitor Management Page", "03-visitors.png",
     "The visitor management page allows administrators to create and manage visitor profiles. Administrators can enter visitor details, upload face images, and store visitor information in the database. These profiles are used by the face recognition module to identify known visitors."),
    (38, "Unknown Visitor Review Page", "04-logs.png",
     "The unknown visitor review page displays visitors who were detected but not successfully identified by the system. It shows the captured image, camera location, detection time, and confidence score. Administrators or security personnel can review the record and assign it to an existing visitor profile or create a new profile."),
    (39, "Visitor Logs and Reports Page", "05-reports.png",
     "The visitor logs and reports page allows users to view complete visitor activity records. Logs can be filtered by date, camera, visitor name, status, and confidence score. This helps administrators and security staff investigate past visitor activity and maintain proper audit records."),
]
for fig_no, title, image, note in screenshots:
    add_figure(doc, fig_no, title, image, note)

doc.save(OUT)
print(OUT)
