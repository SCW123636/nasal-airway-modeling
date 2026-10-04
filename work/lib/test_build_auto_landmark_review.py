# -*- coding: utf-8 -*-
"""Meaningful regression checks for the offline landmark review artifact.

Run with: python -B -m unittest discover -s work/lib -p test_build_auto_landmark_review.py -v
All fixtures are temporary synthetic data and never enter patient directories.
"""

import copy
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import build_auto_landmark_review as review


def fixture():
    return {
        "case": "test_case", "status": "proposals_not_clinically_validated",
        "coordinate_system": "LPS", "unit": "mm",
        "anatomy_frame": {"origin_lps_mm": [0.0, 0.0, 0.0]},
        "notes": [], "review_queue": ["unknown"], "parameters": {},
        "landmarks": {
            "nostril_L": {"label_zh": "左鼻孔入口", "label_en": "left nostril",
                          "status": "proposed", "point_lps_mm": [1.0, 2.5, -3.0],
                          "normal_lps": [0.0, 1.0, 0.0], "consistency_checks": {},
                          "review_reasons": [], "evidence": {}, "overlay_png": "review.png"},
            "unknown": {"label_zh": "待定位", "label_en": "unknown",
                        "status": "unavailable", "point_lps_mm": None, "normal_lps": None,
                        "consistency_checks": {}, "review_reasons": ["unresolved"],
                        "evidence": {}, "overlay_png": "review.png"},
        },
    }


class ReviewBuilderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="nasal_review_test_")
        self.base = Path(self.temp.name)
        self.case_dir = self.base / "test_case"
        self.case_dir.mkdir()
        self.source = self.case_dir / "landmarks.json"
        self.data = fixture()
        self.write()

    def tearDown(self):
        self.temp.cleanup()

    def write(self):
        self.source.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")

    def read(self):
        return review.read_case(self.source, self.base)

    def test_json_script_roundtrip_and_xss_escape(self):
        attack = '</script><img src=x onerror=alert(1)>&\u2028\u2029'
        self.data["notes"] = [attack]
        self.data["landmarks"]["nostril_L"]["label_zh"] = attack
        self.data["landmarks"]["nostril_L"]["evidence"] = {"note": attack}
        self.write()
        summary = review.build_review(self.base)
        html = Path(summary["html"]).read_text(encoding="utf-8")
        embedded = html.split('<script id="review-data" type="application/json">', 1)[1].split('</script>', 1)[0]
        parsed = json.loads(embedded)
        self.assertEqual(parsed["cases"][0]["notes"], [attack])
        self.assertNotIn(attack, html)
        self.assertEqual(html.count('</script>'),
                         (review.HTML_HEAD + review.HTML_TAIL).count('</script>'))
        self.assertNotIn("innerHTML", html)
        self.assertNotIn("fetch(", html)
        self.assertNotIn('src="https:', html)

    def test_hash_changes_with_coordinates_or_anatomy(self):
        first = self.read()
        self.data["landmarks"]["nostril_L"]["point_lps_mm"][0] += 0.5
        self.write()
        second = self.read()
        self.assertNotEqual(first["source_sha256"], second["source_sha256"])
        self.assertNotEqual(first["landmarks"][0]["proposal_sha256"], second["landmarks"][0]["proposal_sha256"])
        self.data["anatomy_frame"]["origin_lps_mm"][2] += 1
        self.write()
        third = self.read()
        self.assertNotEqual(second["landmarks"][0]["proposal_sha256"], third["landmarks"][0]["proposal_sha256"])

    def test_geometry_units_fail_closed(self):
        for field, value in (("coordinate_system", "RAS"), ("unit", "m")):
            with self.subTest(field=field):
                self.data = fixture()
                self.data[field] = value
                self.write()
                with self.assertRaisesRegex(ValueError, "explicit LPS"):
                    self.read()

    def test_invalid_numbers_and_zero_normal_are_rejected(self):
        for field, value in (
            ("point_lps_mm", [1, 2]), ("point_lps_mm", [True, 2, 3]),
            ("point_lps_mm", [1, float("nan"), 3]),
            ("normal_lps", [float("inf"), 1, 0]), ("normal_lps", [0, 0, 0]),
        ):
            with self.subTest(field=field, value=value):
                self.data = fixture()
                self.data["landmarks"]["nostril_L"][field] = value
                self.write()
                with self.assertRaises(ValueError):
                    self.read()

    def test_overlay_path_cannot_escape_case_directory(self):
        for overlay in ("../outside.png", str(self.base.parent / "outside.png")):
            with self.subTest(overlay=overlay):
                self.data["landmarks"]["nostril_L"]["overlay_png"] = overlay
                self.write()
                with self.assertRaisesRegex(ValueError, "inside the case directory"):
                    self.read()

    def test_per_landmark_relative_image_is_encoded(self):
        image = self.case_dir / "点位 图.png"
        image.write_bytes(b"synthetic placeholder; no actual image use")
        self.data["landmarks"]["nostril_L"]["overlay_png"] = image.name
        self.write()
        result = self.read()
        url = result["landmarks"][0]["overlay_url"]
        self.assertTrue(url.startswith("test_case/"))
        self.assertNotIn(" ", url)
        self.assertIn("%20", url)
        self.assertFalse(result["landmarks"][0]["overlay_missing"])

    def test_duplicate_cases_and_missing_sources_are_rejected(self):
        other = self.base / "duplicate"
        other.mkdir()
        (other / "landmarks.json").write_text(json.dumps(self.data), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Duplicate case"):
            review.build_review(self.base)
        with self.assertRaises(FileNotFoundError):
            review.build_review(self.base / "missing")
        with self.assertRaisesRegex(ValueError, "within the input directory"):
            review.build_review(self.base, cases=["../outside"])

    def test_canonical_hash_ignores_dictionary_order(self):
        self.assertEqual(review.sha256_json({"a": 1, "b": 2}), review.sha256_json({"b": 2, "a": 1}))

    def test_review_context_and_navigation_survive_regeneration(self):
        original_source = self.source.read_bytes()
        expected_case = self.read()
        result = review.build_review(self.base)
        html = Path(result["html"]).read_text(encoding="utf-8")
        payload = json.loads(html.split('<script id="review-data" type="application/json">', 1)[1]
                            .split('</script>', 1)[0])
        self.assertIn('href="feedback_review/index.html"', html)
        self.assertIn('查看人工意见核对与局部切面对照', html)
        self.assertIn('跨病例不能直接按统一数值判断解剖部位', html)
        self.assertIn('候选拟合平面与实际切片的交线', html)
        self.assertIn('候选点位与平面方向需要分别复核', html)
        self.assertIn('点左侧任意一张卡片即可切换这里的切片', html)
        self.assertEqual(payload["cases"], [expected_case])
        self.assertEqual(self.source.read_bytes(), original_source)

    @unittest.skipUnless(shutil.which("node"), "Node.js is needed for inline JavaScript regression checks")
    def test_card_focus_and_decision_keep_selected_landmark(self):
        functions = []
        for name in ("finiteTriplet", "formatVector", "label", "englishLabel",
                     "listStrings", "setFocus", "ensureViewerVisible"):
            match = re.search(r"^function " + name + r"\(.*$", review.HTML_TAIL, re.MULTILINE)
            self.assertIsNotNone(match, name)
            functions.append(match.group(0))
        card_function = re.search(r"^function renderCard\(.*?(?=^function renderAdjustment\()",
                                  review.HTML_TAIL, re.MULTILINE | re.DOTALL)
        self.assertIsNotNone(card_function)
        functions.append(card_function.group(0))
        script = r'''
const assert=require("node:assert/strict");
const DATA=FIXTURE;
const STATUS={proposed:"proposed",unavailable:"unavailable"};
const DECISIONS={pending:"pending",accept:"accept",reject:"reject",adjust:"adjust"};
let activeLandmark=null,allCards=[],imageLandmark=null,renderedLandmark=null;
let recordWrites=[],scrollCalls=[];
const viewer={rect:{top:10,bottom:200},getBoundingClientRect(){return this.rect;},scrollIntoView(v){scrollCalls.push(v);}};
const window={innerHeight:800};
const document={querySelectorAll:()=>allCards,querySelector:()=>viewer};
function element(tag,className,text){return {tag,className:className||"",textContent:text,children:[],dataset:{},events:{},attributes:{},
  classList:{toggle(name,value){this[name]=value;}},
  append(...children){this.children.push(...children);},
  setAttribute(name,value){this.attributes[name]=value;},
  addEventListener(name,callback){this.events[name]=callback;}};}
function getRecord(){return {decision:"pending",note:"",updated_at:null};}
function renderImage(c,l){imageLandmark=l.id;}
function render(){renderedLandmark=activeLandmark;}
function decisionRecord(c,l,change){recordWrites.push({id:l.id,...change});}
FUNCTIONS
const c=DATA,l={id:"nostril_L",proposal:DATA.landmarks.nostril_L};
const before=JSON.stringify(DATA);
const card=renderCard(c,l);allCards=[card];
card.events.click({target:{closest:()=>null}});
assert.equal(activeLandmark,l.id,"card body selects candidate");
assert.equal(imageLandmark,l.id,"card body updates slices");
assert.equal(card.classList.focused,true);
assert.equal(recordWrites.length,0,"selection never records a decision");
assert.equal(scrollCalls.length,0,"visible viewer stays in place");
activeLandmark="other";
card.events.click({target:{closest:()=>({})}});
assert.equal(activeLandmark,"other","interactive child retains its own action");
const actions=card.children.find(el=>el.className==="decision");
actions.children.find(el=>el.className==="accept").events.click();
assert.equal(activeLandmark,l.id,"decision selects its candidate before rerender");
assert.equal(renderedLandmark,l.id);
assert.deepEqual(recordWrites,[{id:l.id,decision:"accept"}]);
viewer.rect={top:900,bottom:1200};setFocus(c,l);
assert.deepEqual(scrollCalls,[{block:"start",behavior:"smooth"}],"off-screen viewer is brought into view");
viewer.rect={top:-300,bottom:-10};setFocus(c,l);
assert.equal(scrollCalls.length,2,"viewer above viewport is brought back too");
assert.equal(recordWrites.length,1,"viewer changes never write another decision");
assert.equal(JSON.stringify(DATA),before,"selection and review do not mutate proposals");
process.stdout.write("card interaction checks passed\n");
'''.replace("FIXTURE", json.dumps(self.data, ensure_ascii=False)).replace("FUNCTIONS", "\n".join(functions))
        result = subprocess.run([shutil.which("node")], input=script, text=True, encoding="utf-8",
                                capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("interaction checks passed", result.stdout)

    @unittest.skipUnless(shutil.which("node"), "Node.js is needed for inline JavaScript regression checks")
    def test_inline_javascript_syntax(self):
        js = review.HTML_TAIL.split('<script>', 1)[1].split('</script>', 1)[0]
        result = subprocess.run([shutil.which("node"), "--check"], input=js, text=True,
                                capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(shutil.which("node"), "Node.js is needed for inline JavaScript regression checks")
    def test_import_hash_coordinates_values_and_stale_storage(self):
        case = self.read()
        functions = []
        for name in ("finiteTriplet", "validAdjustment", "safeDecision", "recordKey", "getRecord", "inspectImportedReview"):
            match = re.search(r"^function " + name + r"\(.*$", review.HTML_TAIL, re.MULTILINE)
            self.assertIsNotNone(match, name)
            functions.append(match.group(0))
        record = {
            "landmark_id": "nostril_L", "proposal_sha256": case["landmarks"][0]["proposal_sha256"],
            "original_status": "proposed", "original_point_lps_mm": [1.0, 2.5, -3.0],
            "original_normal_lps": [0.0, 1.0, 0.0], "decision": "accept", "note": "test",
            "updated_at": None,
        }
        imported = {"schema_version": "1.0", "artifact_type": "landmark_review_decisions",
                    "coordinate_system": "LPS", "unit": "mm", "reviewer": None,
                    "cases": [{"case": case["case"], "source_sha256": case["source_sha256"],
                               "decisions": [record]}]}
        prelude = ('const assert=require("node:assert/strict");\n'
                   + "const DATA=" + json.dumps({"cases": [case]}, ensure_ascii=False) + ";\n"
                   + "const input=" + json.dumps(imported, ensure_ascii=False) + ";\n"
                   + 'const VALID_DECISIONS=new Set(["pending","accept","reject","adjust"]);\n'
                   + 'let records={};\n'
                   + "\n".join(functions) + "\n")
        checks = r'''
const clone=()=>structuredClone(input);
const before=JSON.stringify(DATA);
assert.equal(inspectImportedReview(clone()).accepted.length,1);
for (const kind of ["source","proposal","point","normal","status","decision"]) {
  const d=clone(), c=d.cases[0], r=c.decisions[0];
  if(kind==="source")c.source_sha256="stale";
  if(kind==="proposal")r.proposal_sha256="stale";
  if(kind==="point")r.original_point_lps_mm[0]+=1;
  if(kind==="normal")r.original_normal_lps=[1,0,0];
  if(kind==="status")r.original_status="confirmed";
  if(kind==="decision")r.decision="confirmed";
  assert.equal(inspectImportedReview(d).accepted.length,0,kind);
  assert.equal(inspectImportedReview(d).skipped.length,1,kind);
}
for(const invalid of [[NaN,0,1],[Infinity,0,1],[true,0,1],[1,2],null]){
  const d=clone(),r=d.cases[0].decisions[0];r.decision="adjust";
  r.adjusted_point_lps_mm=invalid;r.adjusted_normal_lps=null;
  assert.equal(inspectImportedReview(d).accepted.length,0,"invalid adjustment");
  assert.equal(safeDecision(r),"pending");
}
{
  const d=clone(),r=d.cases[0].decisions[0];r.decision="adjust";
  r.adjusted_point_lps_mm=[1,2,3];r.adjusted_normal_lps=[0,0,0];
  assert.equal(inspectImportedReview(d).accepted.length,0,"zero normal");
  r.adjusted_normal_lps=[0,1,0];
  assert.equal(inspectImportedReview(d).accepted.length,1,"valid adjustment");
}
{
  const d=clone(),l=DATA.cases[0].landmarks[1],r=d.cases[0].decisions[0];
  r.landmark_id=l.id;r.proposal_sha256=l.proposal_sha256;r.original_status="unavailable";
  r.original_point_lps_mm=null;r.original_normal_lps=null;
  assert.equal(inspectImportedReview(d).accepted.length,0,"cannot accept unavailable");
}
{
  const d=clone();d.cases[0].decisions.push(structuredClone(d.cases[0].decisions[0]));
  assert.equal(inspectImportedReview(d).accepted.length,1,"duplicate counted once");
  assert.equal(inspectImportedReview(d).skipped.length,1,"duplicate rejected");
}
{
  const d=clone();d.coordinate_system="RAS";
  assert.throws(()=>inspectImportedReview(d));
}
const c=DATA.cases[0],l=c.landmarks[0];
assert.notEqual(recordKey(c,l),recordKey({...c,source_sha256:"changed"},l));
records[recordKey(c,l)]={decision:"accept",note:"existing review",updated_at:null};
assert.equal(getRecord(c,l).decision,"accept","unchanged source restores its review");
const changedSource={...c,source_sha256:"changed"};
assert.equal(changedSource.landmarks[0].proposal_sha256,l.proposal_sha256,"proposal stays identical in stale-source test");
assert.equal(getRecord(changedSource,l).decision,"pending","changed source must not read an older accept record");
assert.equal(getRecord(c,l).decision,"accept","original-source review remains independently stored");
assert.equal(JSON.stringify(DATA),before,"review must not mutate proposals");
process.stdout.write("import regression checks passed\n");
'''
        result = subprocess.run([shutil.which("node")], input=prelude + checks, text=True,
                                encoding="utf-8", capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("checks passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
