"""Render the spdxify narrated demo: real command output on examples/monorepo + edge-tts narration.

Usage: python demo/render.py [scene numbers]   (needs ffmpeg, edge-tts, Pillow)
"""
import asyncio
import os
import re
import shutil
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BUILD = os.path.join(HERE, "build")
OUT = os.path.join(ROOT, "demo.mp4")
SDKBIN = os.path.join(ROOT, ".venv", "bin")
DEMO = "/tmp/sxdemo/acme"
W, H, FPS = 1280, 720, 24
VOICE = "en-US-AndrewNeural"
MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
MONO_B = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"
SANS_B = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
SANS = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
BG, FG = (24, 26, 33), (220, 223, 228)
ANSI = {"31": (255, 95, 95), "32": (95, 215, 120), "33": (240, 200, 80),
        "2": (130, 135, 145), "36": (90, 200, 230), "35": (200, 140, 230), "1": FG}
PROMPT = "me@laptop ~/acme $ "
TITLEBAR = "~/acme — bash"
REPLAY = {}

SCENES = [
    {
        "kind": "title",
        "title": "spdxify",
        "sub": "move your Python packages to PEP 639 license metadata\nbefore setuptools drops the old forms",
        "say": ("This is S P D X ify, a small open source tool that moves Python packages to the new P E P 639 "
                "license metadata, before setuptools stops accepting the old forms."),
    },
    {
        "kind": "bullets",
        "title": "The problem",
        "bullets": [
            "Every build: \u201cproject.license as a TOML table is deprecated\u201d",
            "   \u201cBy 2027-Feb-18 ... your builds will no longer be supported\u201d",
            "License :: classifiers are deprecated too",
            "Half-migrate (SPDX string + classifier) and setuptools>=77 fails now",
            "\u201cMIT License\u201d isn't SPDX \u00b7 old pinned backends \u00b7 Python 3.8",
            "Open issues in hundreds of repos: matrix-nio, scapy, starship ...",
        ],
        "say": ("Every build of a project with the old license fields prints this warning: the license table is "
                "deprecated, and after February eighteenth 2027 those builds are no longer supported. License "
                "classifiers are deprecated too. The fix looks trivial, but if you switch to an S P D X string and "
                "keep the classifier, setuptools fails the build right now. Free text like M I T License is not "
                "valid, and old pinned backends can't read the new form."),
    },
    {
        "kind": "term",
        "cmds": ["ls", "spdxify verify --no-color 2>&1 | grep -E 'FAIL|OK|Error|deprecated' | sort -u | head -8"],
        "show": ["ls", "spdxify verify"],
        "say": ("Here's a monorepo with six packages and the usual mistakes. spdxify verify builds each package's "
                "metadata with the real setuptools 84 that's installed. One already fails, and the rest print "
                "deprecation warnings."),
    },
    {
        "kind": "term",
        "cmds": ["spdxify check"], "scroll": True,
        "say": ("spdxify check scans the whole repo and explains each problem: license tables, classifiers next "
                "to an S P D X string, which breaks the build today, free text that isn't S P D X, license files "
                "globs that match nothing, and backend pins too old for P E P 639. For each package it works out "
                "the S P D X expression from the metadata and the license file. The B S D classifier plus a "
                "three clause license file becomes B S D 3 clause."),
    },
    {
        "kind": "term",
        "cmds": ["spdxify fix core"],
        "say": ("spdxify fix prints a patch and writes nothing. Comments and layout are kept. The table becomes a "
                "plain string, license files is added, the classifier goes, and setuptools gets a floor of 77."),
    },
    {
        "kind": "term",
        "cmds": ["spdxify fix --write", "spdxify fix gis --license GPL-3.0-or-later --write"],
        "say": ("With dash dash write it applies everything, including set up dot C F G. When it can't tell, it asks "
                "instead of guessing. The G P L classifier and the license text don't say only or or later, so you "
                "pass dash dash license."),
    },
    {
        "kind": "term",
        "cmds": ["spdxify check --fail-on error", "spdxify verify"],
        "say": ("Check again: only one manual note is left, Python 3.8 support. And verify shows clean builds with "
                "License Expression and License File in the metadata."),
    },
    {
        "kind": "term",
        "cmds": ["cat ../spdxify-workflow.yml"],
        "say": ("Add it to C I as a GitHub Action, or as a pre-commit hook, so the old forms don't come back. "
                "Findings show up as annotations on the right lines."),
    },
    {
        "kind": "bullets",
        "title": "spdxify",
        "bullets": [
            "pipx install git+https://github.com/hamarshehmhmd/spdxify",
            "spdxify check  \u00b7  spdxify fix --write  \u00b7  spdxify verify",
            "pyproject.toml \u00b7 setup.cfg \u00b7 setuptools / hatchling / flit / pdm",
            "text / JSON / GitHub annotations \u00b7 GitHub Action \u00b7 pre-commit",
            "github.com/hamarshehmhmd/spdxify",
            "GNU AGPL-3.0-or-later (commercial licenses available)",
        ],
        "say": ("Install it with one pip x line. S P D X ify is licensed under the GNU A G P L version 3 or later, "
                "with commercial licenses available from the author."),
    },
]
async def tts(text, path):
    import edge_tts
    for attempt in range(8):
        try:
            await edge_tts.Communicate(text, VOICE, rate="+4%").save(path)
            return
        except Exception:
            if os.path.exists(path):
                os.remove(path)
            if attempt == 7:
                raise
            await asyncio.sleep(5)


def duration(path):
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
        text=True,
    )
    return float(out.strip())


EXPORTS = {}


def run_cmd(cmd, cwd):
    if cmd.startswith("export ") and "=" in cmd:
        k, v = cmd[7:].split("=", 1)
        EXPORTS[k] = v
        return ""
    env = dict(os.environ, FORCE_COLOR="1", **EXPORTS)
    env.pop("NO_COLOR", None)
    env["PATH"] = os.pathsep.join([SDKBIN, env["PATH"]])
    env["COLUMNS"] = "120"
    p = subprocess.run(
        ["bash", "-c", "shopt -s nullglob; " + cmd],
        cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env,
    )
    return p.stdout.rstrip("\n")


def parse_ansi(line):
    spans, color, bold = [], FG, False
    for part in re.split(r"(\x1b\[[0-9;]*m)", line):
        m = re.match(r"\x1b\[([0-9;]*)m", part)
        if m:
            for code in (m.group(1) or "0").split(";"):
                if code == "0":
                    color, bold = FG, False
                elif code == "1":
                    bold = True
                elif code in ANSI:
                    color = ANSI[code]
        elif part:
            spans.append((part, color, bold))
    return spans


class Term:
    def __init__(self):
        self.font = ImageFont.truetype(MONO, 14)
        self.bold = ImageFont.truetype(MONO_B, 14)
        self.cw = self.font.getlength("M")
        self.lh = 20
        self.cols = int((W - 80) / self.cw)

    def wrap(self, spans):
        lines, cur, n = [], [], 0
        for text, c, b in spans:
            while text:
                room = self.cols - n
                if room <= 4:
                    lines.append(cur); cur, n = [], 0
                    text = "    " + text.lstrip(" ")
                    room = self.cols
                if len(text) <= room:
                    cur.append((text, c, b)); n += len(text); text = ""
                else:
                    cut = text.rfind(" ", 0, room + 1)
                    cut = cut if cut > 4 else room
                    cur.append((text[:cut], c, b)); lines.append(cur); cur, n = [], 0
                    text = "    " + text[cut:].lstrip(" ")
        lines.append(cur)
        return lines

    def frame(self, lines, cursor=False):
        img = Image.new("RGB", (W, H), BG)
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([20, 14, W - 20, H - 14], 12, fill=(30, 33, 41), outline=(60, 64, 76))
        for i, c in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
            d.ellipse([40 + i * 24, 30, 54 + i * 24, 44], fill=c)
        d.text((W // 2, 37), TITLEBAR, font=ImageFont.truetype(SANS, 15), fill=(150, 155, 165), anchor="mm")
        visible = lines[-30:]
        y = 64
        for ln in visible:
            x = 40
            for text, c, b in ln:
                d.text((x, y), text, font=self.bold if b else self.font, fill=c)
                x += self.cw * len(text)
            y += self.lh
        if cursor:
            last = visible[-1] if visible else []
            x = 40 + self.cw * sum(len(t) for t, _, _ in last)
            d.rectangle([x, y - self.lh + 3, x + self.cw - 2, y - 4], fill=FG)
        return img


def card(scene):
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    if scene["kind"] == "title":
        d.text((W // 2, 280), scene["title"], font=ImageFont.truetype(MONO_B, 78), fill=(95, 215, 120), anchor="mm")
        d.multiline_text((W // 2, 420), scene["sub"], font=ImageFont.truetype(SANS, 32), fill=FG, anchor="mm",
                         align="center", spacing=12)
        d.text((W // 2, 620), "github.com/hamarshehmhmd/spdxify  ·  check · fix · verify  ·  GNU AGPL-3.0",
               font=ImageFont.truetype(SANS, 20), fill=(150, 155, 165), anchor="mm")
    else:
        d.text((90, 90), scene["title"], font=ImageFont.truetype(SANS_B, 52), fill=(95, 215, 120))
        f = ImageFont.truetype(SANS, 29)
        y = 200
        for b in scene["bullets"]:
            if b and not b.startswith("   "):
                d.text((90, y), "•", font=f, fill=(240, 200, 80))
            d.text((130, y), b.strip(), font=f, fill=FG)
            y += 58 if b.startswith("   ") or not b else 62
    return img


class Writer:
    def __init__(self, path, audio):
        self.p = subprocess.Popen(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
             "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-i", audio,
             "-af", "apad", "-c:v", "libx264", "-preset", "medium", "-crf", "23",
             "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
             "-shortest", path],
            stdin=subprocess.PIPE,
        )
        self.n = 0

    def put(self, img, count=1):
        data = img.tobytes()
        for _ in range(count):
            self.p.stdin.write(data)
        self.n += count

    def close(self):
        self.p.stdin.close()
        self.p.wait()
        if self.p.returncode:
            sys.exit("ffmpeg failed")


def _cap_output(out, tail=False):
    lines = out.splitlines()
    if tail and len(lines) > 26:
        return "\n".join(["…"] + lines[-25:])
    if len(lines) > 24:
        lines = lines[:22] + ["…", lines[-1]]
    return "\n".join(lines)


def render_scene(i, scene, workdir):
    audio = os.path.join(BUILD, f"s{i}.mp3")
    if not os.path.exists(audio):
        asyncio.run(tts(scene["say"], audio))
    total = int((duration(audio) + 0.7) * FPS)
    path = os.path.join(BUILD, f"s{i}.mp4")
    w = Writer(path, audio)
    if scene["kind"] != "term":
        w.put(card(scene), total)
        w.close()
        return path
    t = Term()
    shown = scene.get("show", scene["cmds"])
    wd = workdir
    if scene.get("replay"):
        outputs = [REPLAY[c] for c in scene["cmds"]]
    else:
        outputs = [run_cmd(c, wd) if scene.get("scroll") else _cap_output(run_cmd(c, wd), scene.get("tail")) for c in scene["cmds"]]
    # If show has more lines than cmds (a command displayed as several visual lines
    # that map to one executed command), join show into one typed command per output.
    if len(shown) != len(outputs):
        if len(outputs) == 1:
            shown = [" ".join(s.rstrip("\\").strip() for s in shown)]
        elif len(shown) > len(outputs):
            # first N-1 outputs map 1:1; remaining show lines are the last command
            shown = list(shown[: len(outputs) - 1]) + [
                " ".join(s.rstrip("\\").strip() for s in shown[len(outputs) - 1 :])
            ]
    steps = list(zip(shown, outputs))
    typing = sum(len(s) for s, _ in steps) / 32 * FPS
    pause = max(6, int((total - typing) / max(1, len(steps))) - 4)
    lines = []
    for cmd, out in steps:
        prompt = [(scene.get("prompt", PROMPT), (95, 215, 120), True)]
        for k in range(0, len(cmd) + 1, 2):
            frame = t.frame(lines + t.wrap(prompt + [(cmd[:k], FG, False)]), cursor=True)
            w.put(frame)
        lines += t.wrap(prompt + [(cmd, FG, False)])
        outl = []
        for ol in out.splitlines():
            outl += t.wrap(parse_ansi(ol))
        hold = min(pause, max(0, total - w.n))
        if scene.get("scroll") and len(outl) > 28:
            # reveal the output gradually so the narration can walk through it
            reveal = int(hold * scene.get("reveal", 0.8))
            for f in range(reveal):
                k = 28 + int((len(outl) - 28) * (f + 1) / reveal)
                w.put(t.frame(lines + outl[:k]))
            hold -= reveal
        lines += outl
        lines.append([])
        w.put(t.frame(lines), max(0, hold))
    final = t.frame(lines + t.wrap([(scene.get("prompt", PROMPT), (95, 215, 120), True)]), cursor=True)
    if w.n < total:
        w.put(final, total - w.n)
    w.close()
    return path






def setup():
    shutil.rmtree("/tmp/sxdemo", ignore_errors=True)
    os.makedirs("/tmp/sxdemo")
    shutil.copytree(os.path.join(ROOT, "examples", "monorepo"), DEMO)
    shutil.copy(os.path.join(ROOT, "examples", "spdxify-workflow.yml"), "/tmp/sxdemo/spdxify-workflow.yml")
    g = ["git", "-C", DEMO]
    subprocess.run(g + ["init", "-q"], check=True)
    subprocess.run(g + ["add", "-A"], check=True)
    subprocess.run(g + ["-c", "user.name=me", "-c", "user.email=me@example.com", "commit", "-qm", "acme"], check=True)
    EXPORTS["GIT_PAGER"] = "cat"


def main():
    os.makedirs(BUILD, exist_ok=True)
    setup()
    only = [int(x) for x in sys.argv[1:]]
    parts = []
    for i, s in enumerate(SCENES):
        if not only or i in only:
            parts.append(render_scene(i, s, DEMO))
        else:
            parts.append(os.path.join(BUILD, "s%d.mp4" % i))
    with open(os.path.join(BUILD, "list.txt"), "w") as fh:
        fh.writelines(f"file '{p}'\n" for p in parts)
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i",
         os.path.join(BUILD, "list.txt"), "-c:v", "libx264", "-crf", "23", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", OUT],
        check=True,
    )
    with open(os.path.join(BUILD, "narration.txt"), "w") as fh:
        fh.write("\n\n".join(s["say"] for s in SCENES) + "\n")
    print(OUT, round(duration(OUT), 1), "s")


if __name__ == "__main__":
    main()
