#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Build an offline, auditable review page for automatic landmark proposals.

The page records review decisions only. It does not modify proposals, confirm
planes, crop an airway, or write CFD inputs. Uses Python's standard library.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from datetime import datetime
from pathlib import Path
from urllib.parse import quote


PREFERRED_CASE_ORDER = ("p0", "p1", "p2", "p3", "p3t1", "p3_t2", "p3_t1")
PROPOSAL_STATUSES = {"proposed", "needs_review", "unavailable"}


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def sha256_json(value):
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def script_json(value):
    """Keep arbitrary JSON strings inside one inert application/json element."""
    return (canonical_json(value).replace("&", "\\u0026")
            .replace("<", "\\u003c").replace(">", "\\u003e")
            .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


def finite_triplet(value):
    return (isinstance(value, list) and len(value) == 3
            and all(isinstance(n, (int, float)) and not isinstance(n, bool)
                    and math.isfinite(n) for n in value))


def reject_constant(value):
    raise ValueError("Non-finite JSON number: " + value)


def read_case(source, output_parent):
    raw_bytes = source.read_bytes()
    data = json.loads(raw_bytes.decode("utf-8-sig"), parse_constant=reject_constant)
    if not isinstance(data, dict) or not isinstance(data.get("landmarks"), dict):
        raise ValueError(f"{source}: expected an object with a landmarks object")
    if data.get("coordinate_system") != "LPS" or data.get("unit") != "mm":
        raise ValueError(f"{source}: review requires explicit LPS coordinates and mm units")
    case_id = str(data.get("case", source.parent.name))
    landmarks = []
    for key, proposal in data["landmarks"].items():
        if not isinstance(proposal, dict):
            raise ValueError(f"{source}: landmark {key} is not an object")
        if proposal.get("status") not in PROPOSAL_STATUSES:
            raise ValueError(f"{source}: landmark {key} has an unsupported status")
        for field in ("point_lps_mm", "normal_lps"):
            value = proposal.get(field)
            if value is not None and not finite_triplet(value):
                raise ValueError(f"{source}: {key}.{field} must be null or three finite numbers")
        normal = proposal.get("normal_lps")
        if normal is not None and sum(float(n) ** 2 for n in normal) < 1e-16:
            raise ValueError(f"{source}: {key}.normal_lps must be nonzero")
        image_url = None
        image_missing = False
        image_name = proposal.get("overlay_png") or "review.png"
        if not isinstance(image_name, str):
            raise ValueError(f"{source}: {key}.overlay_png must be a relative path string")
        image_path = (source.parent / image_name).resolve()
        if not image_path.is_relative_to(source.parent.resolve()):
            raise ValueError(f"{source}: overlay path must stay inside the case directory")
        if image_path.is_file():
            relative_image = os.path.relpath(image_path, output_parent).replace(os.sep, "/")
            image_url = quote(relative_image, safe="/.-_")
        else:
            image_missing = True
        hash_input = {
            "case": case_id, "coordinate_system": "LPS", "unit": "mm",
            "anatomy_frame": data.get("anatomy_frame"),
            "landmark_id": key, "proposal": proposal,
        }
        landmarks.append({
            "id": key, "proposal": proposal,
            "proposal_sha256": sha256_json(hash_input),
            "overlay_url": image_url, "overlay_missing": image_missing,
        })
    return {
        "case": case_id, "source_file": source.parent.name + "/landmarks.json",
        "source_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "status": data.get("status"), "coordinate_system": "LPS", "unit": "mm",
        "anatomy_frame": data.get("anatomy_frame"),
        "notes": data.get("notes", []), "review_queue": data.get("review_queue", []),
        "parameters": data.get("parameters", {}), "landmarks": landmarks,
        "coarse_localization": data.get("coarse_localization"),
        "coarse_adjustment": data.get("coarse_adjustment"),
    }


HTML_HEAD = r'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light">
<title>鼻腔解剖定位 · 候选复核</title>
<style>
:root{--bg:#f5f4f0;--panel:#fffefa;--ink:#213447;--muted:#64758a;--line:#d9e0e5;--blue:#245879;--light:#e8f0f6;--warn:#875717;--warnbg:#fff2d9;--danger:#954439;--good:#37624c}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.6 system-ui,-apple-system,"Segoe UI","Microsoft YaHei",sans-serif}button,input,textarea,select{font:inherit}button{cursor:pointer}button:disabled{cursor:not-allowed;opacity:.5}button,input,textarea,select{border:1px solid var(--line);border-radius:8px;background:#fff;color:var(--ink)}button{padding:8px 13px}button:hover:not(:disabled){border-color:var(--blue)}button:focus-visible,input:focus-visible,textarea:focus-visible,select:focus-visible{outline:3px solid #82afcd;outline-offset:2px}button.primary{background:var(--blue);border-color:var(--blue);color:white}button.soft{background:var(--light);color:var(--blue)}input,textarea,select{padding:8px 10px}textarea{width:100%;resize:vertical;min-height:70px}h1,h2,h3,p{margin:0}h1{font-size:25px;letter-spacing:.02em}h2{font-size:20px}h3{font-size:17px}small,.muted{color:var(--muted)}.mono{font-family:ui-monospace,Consolas,monospace;overflow-wrap:anywhere}.top{padding:24px 30px 20px;background:var(--panel);border-bottom:1px solid var(--line)}.topline{display:flex;justify-content:space-between;align-items:center;gap:20px;flex-wrap:wrap}.eyebrow{font-size:12px;letter-spacing:.15em;color:var(--muted);margin-bottom:5px}.subtitle{color:var(--muted);margin-top:8px;max-width:950px}.notice{margin-top:15px;border-left:3px solid #9eb4c4;padding:9px 13px;background:#f0f3f5;font-size:13px}.toolbar{display:flex;align-items:center;gap:10px;flex-wrap:wrap}.toolbar input{width:145px}.layout{max-width:1750px;margin:auto;display:grid;grid-template-columns:210px minmax(0,1fr);gap:23px;padding:23px 28px}.sidebar{align-self:start;position:sticky;top:15px}.case-list{display:flex;flex-direction:column;gap:9px}.case-button{text-align:left;background:var(--panel);padding:13px 14px}.case-button.active{background:var(--blue);color:#fff;border-color:var(--blue)}.case-button.active small{color:#d8e4ed}.case-button strong{display:block}.case-button small{display:block;font-size:12px}.sidebar-note{margin-top:16px;color:var(--muted);font-size:12px}.progress{height:4px;border-radius:5px;background:#d6e0e5;margin-top:9px;overflow:hidden}.progress span{display:block;background:#86a8bb;height:100%}.case-header{display:flex;justify-content:space-between;align-items:flex-start;gap:14px;margin-bottom:15px}.case-meta{margin-top:4px;color:var(--muted);font-size:13px}.filter-row{display:flex;gap:12px;align-items:center;flex-wrap:wrap;font-size:13px;margin:13px 0 18px}.filter-row label{display:flex;gap:6px;align-items:center}.content-grid{display:grid;grid-template-columns:minmax(300px,1fr) minmax(330px,1.05fr);gap:18px;align-items:start}.cards{display:flex;flex-direction:column;gap:13px}.card{padding:17px;background:var(--panel);border:1px solid var(--line);border-radius:12px}.card.focused{border-color:#6d94af;box-shadow:0 0 0 2px #d8e6f0}.card-head{display:flex;gap:10px;justify-content:space-between;align-items:start}.card-head h3 button{padding:0;border:0;background:transparent;color:var(--ink);text-align:left}.label-en{font-size:12px;color:var(--muted);margin-top:2px}.badge{display:inline-block;padding:3px 8px;border-radius:5px;background:var(--light);color:var(--blue);font-size:12px;white-space:nowrap}.badge.warning{background:var(--warnbg);color:var(--warn)}.badge.unavailable{background:#eee9e7;color:#765b51}.badge.reviewed{background:#e9f0eb;color:var(--good)}.reasons{font-size:13px;color:var(--warn);margin:10px 0;padding-left:19px}.coord{display:flex;justify-content:space-between;gap:10px;align-items:center;background:#f3f5f6;padding:9px 10px;border-radius:7px;margin:12px 0 8px}.coord .mono{font-size:13px}.coord small{display:block}.coord button{font-size:12px;padding:5px 8px;flex-shrink:0}.normal{font-size:12px;color:var(--muted)}.decision{display:flex;gap:6px;flex-wrap:wrap;margin:13px 0 10px}.decision button{padding:7px 10px;font-size:13px}.decision button.selected{background:var(--blue);color:#fff;border-color:var(--blue)}.decision button.reject.selected{background:var(--danger);border-color:var(--danger)}.decision button.pending.selected{background:#e3e8ec;border-color:#bac8d1;color:var(--ink)}.adjust{background:#f2f5f7;border-radius:7px;padding:11px;margin-bottom:10px}.adjust label{font-size:12px;display:block;margin-bottom:6px}.triplet{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:6px;margin-bottom:10px}.triplet input{width:100%;padding:7px;font-size:13px}.validation{font-size:12px;color:var(--danger);margin-top:5px}.details{margin-top:11px;font-size:12px}.details summary{cursor:pointer;color:var(--blue)}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f2f4f5;border-radius:6px;padding:10px;max-height:260px;overflow:auto;font-size:12px}.note-label{display:block;font-size:12px;color:var(--muted);margin-bottom:5px}.card textarea{font-size:13px;min-height:55px}.saved-time{font-size:11px;color:var(--muted);margin-top:5px}.viewer{position:sticky;top:15px;background:var(--panel);border:1px solid var(--line);border-radius:12px;overflow:hidden}.viewer-head{padding:16px 17px 12px;border-bottom:1px solid var(--line)}.viewer-head p{font-size:12px;color:var(--muted);margin-top:5px}.image-wrap{padding:10px;background:#e9edf0;min-height:180px;display:flex;align-items:center;justify-content:center}.image-wrap img{display:block;max-width:100%;height:auto;cursor:zoom-in}.image-caption{padding:11px 16px;font-size:12px;color:var(--muted)}.case-notes{margin-top:16px;padding:13px 15px;font-size:13px;background:var(--panel);border:1px solid var(--line);border-radius:9px}.case-notes summary{cursor:pointer;color:var(--blue)}.case-notes ul{padding-left:18px;margin:8px 0}.empty{padding:35px;text-align:center;color:var(--muted);background:var(--panel);border:1px dashed var(--line);border-radius:12px}.toast{position:fixed;bottom:24px;left:50%;transform:translateX(-50%);background:#22394c;color:white;padding:10px 18px;border-radius:8px;z-index:20;max-width:90vw;box-shadow:0 3px 14px #0002}.save-warning{color:var(--danger);font-size:12px;min-height:18px}.lightbox{position:fixed;inset:0;z-index:50;background:#112435ec;display:flex;flex-direction:column}.lightbox-bar{padding:10px 16px;display:flex;gap:10px;align-items:center;color:#fff;flex-wrap:wrap}.lightbox-bar span{margin-right:auto}.lightbox-image{flex:1;overflow:auto;padding:15px;text-align:center}.lightbox-image img{display:inline-block;max-width:100%;height:auto;vertical-align:top}.lightbox-image.actual img{max-width:none}.footer{margin-top:20px;color:var(--muted);font-size:12px} [hidden]{display:none!important}
@media(max-width:1100px){.content-grid{grid-template-columns:minmax(0,1fr)}.viewer{position:static;grid-row:1}.image-wrap img{max-height:650px}.layout{grid-template-columns:160px minmax(0,1fr);padding:18px;gap:15px}}
@media(max-width:700px){.top{padding:18px}.layout{display:block;padding:14px}.sidebar{position:static;margin-bottom:17px}.case-list{display:grid;grid-template-columns:repeat(2,minmax(0,1fr))}.sidebar-note{display:none}.content-grid{display:block}.viewer{margin-bottom:15px}.card{padding:14px}.case-header{display:block}.case-header .badge{margin-top:8px}.toolbar{margin-top:10px}h1{font-size:22px}}
/* 整张卡片可点选；窄屏切片图常驻可见。 */
.card{cursor:pointer;transition:border-color .12s,box-shadow .12s}
.card:hover{border-color:#9dbdd4}
.card.focused{border-color:var(--blue);box-shadow:0 0 0 3px #cfe0ed}
.card-head h3 button{color:var(--blue);text-decoration:underline dotted;text-underline-offset:3px}
.card-head h3 button:hover{color:#123a52;text-decoration-style:solid}
.viewer-head .hint{font-size:12px;color:var(--blue);margin-top:6px}
@media(max-width:1100px){.viewer{position:sticky;top:0;z-index:6;grid-row:1;box-shadow:0 4px 14px rgba(33,52,71,.12)}.image-wrap img{max-height:42vh;object-fit:contain}.viewer-head{padding:11px 14px 9px}.viewer-head p:not(.hint){display:none}}
.review-context{margin-top:12px;font-size:13px;max-width:1080px}.feedback-link{display:inline-block;margin-top:10px;padding:8px 13px;border:1px solid var(--blue);border-radius:8px;background:var(--light);color:var(--blue);font-weight:600;text-decoration:none}.feedback-link:hover{background:#dbe8f2}.feedback-link:focus-visible{outline:3px solid #82afcd;outline-offset:2px}
</style><script src="/workspace/embed.js" defer></script></head><body>
<header class="top"><div class="topline"><div><div class="eyebrow">CT · ANATOMICAL LANDMARK REVIEW</div><h1>鼻腔自动标定 · 候选复核</h1></div>
<div class="toolbar"><label for="reviewer" class="muted">复核人</label><input id="reviewer" autocomplete="off" placeholder="可选"><button id="import" class="soft">导入审核记录</button><input id="import-file" type="file" accept=".json,application/json" hidden><button id="export" class="primary">下载审核记录</button></div></div>
<p class="subtitle">自动结果已按需复核项优先排列。点选候选、查看切片，记录接受、拒绝或调整；未操作的点位始终保持待处理。</p>
<div class="notice">接受候选仅表示本页审核记录，尚未回写分割、裁剪面或 CFD。候选状态与原始坐标保持原样。局部储存依赖当前浏览器，请下载 JSON 留存；更换浏览器或清理缓存后记录可能不可用。</div>
<p class="review-context"><strong>读图与坐标：</strong>绝对 XYZ 是本次扫描的物理坐标，跨病例不能直接按统一数值判断解剖部位。虚线是候选拟合平面与实际切片的交线，并非自动确定的解剖切线；候选点位与平面方向需要分别复核。</p>
<a class="feedback-link" href="feedback_review/index.html">查看人工意见核对与局部切面对照</a>
<div id="save-warning" class="save-warning" role="status"></div></header>
<div id="import-preview" class="notice" style="margin:16px 28px 0" hidden><p id="import-summary"></p><div class="toolbar" style="margin-top:10px"><label><input id="import-overwrite" type="checkbox"> 覆盖已有审核（仅限原候选完全匹配）</label><button id="apply-import" class="primary">导入匹配记录</button><button id="cancel-import">取消</button></div></div>
<main class="layout"><aside class="sidebar"><nav id="case-list" class="case-list" aria-label="病例切换"></nav><p class="sidebar-note">LPS 坐标，单位 mm：<br>L 向患者左侧为正<br>P 向患者后方为正<br>S 向患者上方为正<br><br>坐标描述算法候选；页面不提供临床置信概率。</p></aside>
<section><div class="case-header"><div><h2 id="case-title"></h2><p id="case-meta" class="case-meta"></p></div><span id="case-progress" class="badge"></span></div>
<p id="coarse-summary" class="muted" style="font-size:13px"></p>
<div class="filter-row"><label for="filter">显示</label><select id="filter"><option value="all">全部候选</option><option value="attention">需重点复核</option><option value="pending">尚未处理</option><option value="reviewed">已记录决定</option></select><input id="point-search" type="search" placeholder="搜索点位名称或编号" aria-label="筛选点位"><label><input id="priority" type="checkbox" checked> 异常优先</label><span id="visible-count" class="muted"></span></div>
<div class="content-grid"><div id="cards" class="cards"></div><aside class="viewer"><div class="viewer-head"><h3 id="viewer-title">切片复核图</h3><p>从左到右为索引轴向、冠状、矢状切面。十字为候选点投影，虚线为平面与实际切片的交线。点击图像放大。</p><p class="hint">点左侧任意一张卡片即可切换这里的切片。</p></div><div id="image-wrap" class="image-wrap"></div><div id="image-caption" class="image-caption"></div></aside></div>
<details id="case-notes" class="case-notes"><summary>病例备注、解剖坐标系与生成参数</summary><div id="case-detail"></div></details>
<p id="footer" class="footer"></p></section></main>
<div id="toast" class="toast" role="status" hidden></div>
<div id="lightbox" class="lightbox" role="dialog" aria-modal="true" aria-label="放大复核图" hidden><div class="lightbox-bar"><span id="lightbox-title"></span><button id="zoom-fit">适应窗口</button><button id="zoom-actual">原始像素</button><button id="close-lightbox">关闭（Esc）</button></div><div id="lightbox-image" class="lightbox-image"><img id="large-image" alt="放大复核图"></div></div>
<script id="review-data" type="application/json">'''


HTML_TAIL = r'''</script>
<script>
"use strict";
const DATA=JSON.parse(document.getElementById("review-data").textContent);
const $=id=>document.getElementById(id);
const STATUS={proposed:"已提出候选",needs_review:"需重点复核",unavailable:"无法自动定位"};
const DECISIONS={pending:"待处理",accept:"接受候选",reject:"拒绝候选",adjust:"调整坐标"};
const VALID_DECISIONS=new Set(Object.keys(DECISIONS));
const storageKey="nasal_landmark_review_v1_"+DATA.workspace_key;
let records={},activeCase=0,activeLandmark=null,storageAvailable=true,toastTimer=null,previousFocus=null,pendingImport=null;
function element(tag,className,text){const el=document.createElement(tag);if(className)el.className=className;if(text!==undefined)el.textContent=String(text);return el;}
function finiteTriplet(v){return Array.isArray(v)&&v.length===3&&v.every(x=>typeof x==="number"&&Number.isFinite(x));}
function recordKey(c,l){return c.case+":"+c.source_sha256+":"+l.id+":"+l.proposal_sha256;}
function getRecord(c,l){const value=records[recordKey(c,l)];return value&&VALID_DECISIONS.has(value.decision)?value:{decision:"pending",note:"",updated_at:null};}
function safeDecision(record){return record.decision==="adjust"&&!validAdjustment(record)?"pending":record.decision;}
function validAdjustment(r){return finiteTriplet(r.adjusted_point_lps_mm)&&(r.adjusted_normal_lps===null||r.adjusted_normal_lps===undefined||(finiteTriplet(r.adjusted_normal_lps)&&Math.hypot(...r.adjusted_normal_lps)>1e-8));}
function toast(message){$("toast").textContent=message;$("toast").hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>{$("toast").hidden=true;},3200);}
function save(){try{localStorage.setItem(storageKey,JSON.stringify({schema_version:1,reviewer:$("reviewer").value,records}));storageAvailable=true;$("save-warning").textContent="";}catch(error){storageAvailable=false;$("save-warning").textContent="浏览器无法保存本地记录。当前页面仍可复核，请在关闭页面前下载审核记录。";}}
try{const raw=localStorage.getItem(storageKey);if(raw){const stored=JSON.parse(raw);if(stored&&stored.schema_version===1&&stored.records&&typeof stored.records==="object"){records=stored.records;$("reviewer").value=typeof stored.reviewer==="string"?stored.reviewer:"";}}}catch(error){storageAvailable=false;$("save-warning").textContent="本地记录未能读取。请完成复核后下载审核记录。";}
function attention(l){return l.proposal.status!=="proposed"||(Array.isArray(l.proposal.review_reasons)&&l.proposal.review_reasons.length>0);}
function priority(l){return l.proposal.status==="needs_review"?0:l.proposal.status==="unavailable"?1:attention(l)?2:3;}
function reviewedCount(c){return c.landmarks.filter(l=>safeDecision(getRecord(c,l))!=="pending").length;}
function refreshCaseList(){const nav=$("case-list");nav.replaceChildren();DATA.cases.map((c,i)=>({c,i})).sort((a,b)=>b.c.landmarks.filter(attention).length-a.c.landmarks.filter(attention).length).forEach(({c,i})=>{const done=reviewedCount(c),count=c.landmarks.length;const b=element("button","case-button"+(i===activeCase?" active":""));b.type="button";b.setAttribute("aria-current",i===activeCase?"true":"false");b.append(element("strong",null,c.case),element("small",null,`${done} / ${count} 已记录 · ${c.landmarks.filter(attention).length} 项需重点复核`));const bar=element("div","progress"),fill=element("span");fill.style.width=(count?100*done/count:0)+"%";bar.append(fill);b.append(bar);b.addEventListener("click",()=>{activeCase=i;activeLandmark=null;render();});nav.append(b);});const c=DATA.cases[activeCase];if(c)$("case-progress").textContent=`${reviewedCount(c)} / ${c.landmarks.length} 已记录`;}
function formatVector(v){return finiteTriplet(v)?v.map(x=>x.toFixed(3)).join(", "):"未定位";}
function label(l){return l.proposal.label_zh||l.id;}
function englishLabel(l){return l.proposal.label_en||l.id;}
function listStrings(v){if(v===null||v===undefined)return [];if(Array.isArray(v))return v.map(x=>typeof x==="string"?x:JSON.stringify(x));return [typeof v==="string"?v:JSON.stringify(v)];}
function render(){const c=DATA.cases[activeCase];if(!c)return;refreshCaseList();renderCoarseSummary(c);$("case-title").textContent=c.case+" · 解剖候选";const caseStatus={proposals_not_clinically_validated:"候选待验证",provisional:"暂定结果",needs_review:"需复核"}[c.status]||c.status||"未提供";$("case-meta").textContent=`原始坐标 LPS · 统一坐标 UAS · 单位 mm · 原始状态：${caseStatus}`;const view=$("filter").value,query=$("point-search").value.trim().toLocaleLowerCase();let visible=c.landmarks.filter(l=>(view==="attention"?attention(l):view==="pending"?safeDecision(getRecord(c,l))==="pending":view==="reviewed"?safeDecision(getRecord(c,l))!=="pending":true)&&(!query||[label(l),englishLabel(l),l.id].join(" ").toLocaleLowerCase().includes(query)));if($("priority").checked)visible=visible.slice().sort((a,b)=>priority(a)-priority(b));$("visible-count").textContent=`显示 ${visible.length} / ${c.landmarks.length} 项`;if(!visible.some(l=>l.id===activeLandmark))activeLandmark=visible.length?visible[0].id:null;const cards=$("cards");cards.replaceChildren();visible.forEach(l=>cards.append(renderCard(c,l)));if(!visible.length)cards.append(element("div","empty","当前筛选下没有候选。"));const selected=c.landmarks.find(l=>l.id===activeLandmark);renderImage(c,selected);renderCaseDetail(c);$("footer").textContent=`生成时间：${DATA.generated_at} · 所有图像与数据来自本地文件 · 导出的审核记录需要由后续流程单独核验后使用。`;}
function setFocus(c,l){activeLandmark=l.id;document.querySelectorAll(".card").forEach(el=>el.classList.toggle("focused",el.dataset.landmark===l.id));renderImage(c,l);ensureViewerVisible();}
function ensureViewerVisible(){const v=document.querySelector(".viewer");if(!v)return;const r=v.getBoundingClientRect();if(r.bottom<=8||r.top>=window.innerHeight-8)v.scrollIntoView({block:"start",behavior:"smooth"});}
function decisionRecord(c,l,change){const next={...getRecord(c,l),...change,updated_at:new Date().toISOString()};records[recordKey(c,l)]=next;save();refreshCaseList();return next;}
function renderCard(c,l){const p=l.proposal,r=getRecord(c,l),card=element("article","card"+(l.id===activeLandmark?" focused":""));card.dataset.landmark=l.id;const head=element("div","card-head"),names=element("div"),h=element("h3"),focus=element("button",null,label(l));focus.type="button";focus.addEventListener("click",()=>setFocus(c,l));h.append(focus);names.append(h,element("div","label-en",englishLabel(l)));head.append(names,element("span","badge"+(p.status==="needs_review"?" warning":p.status==="unavailable"?" unavailable":""),STATUS[p.status]));card.append(head);const reasons=listStrings(p.review_reasons);if(reasons.length){const ul=element("ul","reasons");reasons.forEach(s=>ul.append(element("li",null,s)));card.append(ul);}const coord=element("div","coord"),coordText=element("div");coordText.append(element("small",null,"原始候选 · [L, P, S] mm"),element("div","mono",formatVector(p.point_lps_mm)));coord.append(coordText);const copy=element("button",null,"复制坐标");copy.type="button";copy.disabled=!finiteTriplet(p.point_lps_mm);copy.addEventListener("click",()=>copyText(JSON.stringify({coordinate_system:"LPS",unit:"mm",landmark_id:l.id,point_lps_mm:p.point_lps_mm,normal_lps:p.normal_lps??null},null,2)));coord.append(copy);card.append(coord);const adjustment=c.coarse_adjustment?.landmarks?.[l.id];if(adjustment?.coarse){const coarseText=element("div","normal");coarseText.textContent=`粗调 UAS ${formatVector(adjustment.coarse.point_uas_mm)} · 归一化 ${formatVector(adjustment.coarse.point_uas_normalized)} · 精调偏移 ${adjustment.delta?adjustment.delta.distance_uas_mm.toFixed(2)+" mm":"待精调"}`;card.append(coarseText);}card.append(element("div","normal","原始法向 [L, P, S]："+(finiteTriplet(p.normal_lps)?formatVector(p.normal_lps):"未提供")));
const actions=element("div","decision");for(const [value,text]of Object.entries(DECISIONS)){const b=element("button",value+(r.decision===value?" selected":""),text);b.type="button";b.setAttribute("aria-pressed",String(r.decision===value));b.disabled=value==="accept"&&(!finiteTriplet(p.point_lps_mm)||p.status==="unavailable");if(b.disabled)b.title="未得到可用候选坐标，不能直接接受";b.addEventListener("click",()=>{activeLandmark=l.id;let update={decision:value};if(value==="adjust"&&!finiteTriplet(r.adjusted_point_lps_mm)){update.adjusted_point_lps_mm=finiteTriplet(p.point_lps_mm)?p.point_lps_mm.slice():null;update.adjusted_normal_lps=finiteTriplet(p.normal_lps)?p.normal_lps.slice():null;}decisionRecord(c,l,update);render();});actions.append(b);}card.append(actions);
if(r.decision==="adjust")card.append(renderAdjustment(c,l,r));const noteLabel=element("label","note-label","复核备注（可选）"),note=element("textarea");note.value=typeof r.note==="string"?r.note:"";note.placeholder="记录判断依据或仍需检查的结构";note.setAttribute("aria-label",label(l)+"复核备注");note.addEventListener("change",()=>{decisionRecord(c,l,{note:note.value});time.textContent="已记录："+new Date().toLocaleString();});card.append(noteLabel,note);const time=element("div","saved-time",r.updated_at?"已记录："+new Date(r.updated_at).toLocaleString():"尚未记录审核决定");card.append(time);const details=element("details","details"),summary=element("summary",null,"查看一致性检查与候选证据"),pre=element("pre","mono");pre.textContent=JSON.stringify({coarse_prior:p.coarse_prior??null,consistency_checks:p.consistency_checks??{},evidence:p.evidence??{},proposal_sha256:l.proposal_sha256},null,2);details.append(summary,pre);card.append(details);card.addEventListener("click",event=>{if(event.target.closest("button,input,textarea,select,summary,a"))return;setFocus(c,l);});return card;}
function renderAdjustment(c,l,r){const box=element("div","adjust");box.append(element("label",null,"调整后坐标 [L, P, S]，单位 mm"));const pointRow=element("div","triplet"),pointInputs=[];["L","P","S"].forEach((axis,i)=>{const input=element("input");input.type="number";input.step="any";input.placeholder=axis;input.setAttribute("aria-label",label(l)+"调整后"+axis+"坐标");input.value=finiteTriplet(r.adjusted_point_lps_mm)?r.adjusted_point_lps_mm[i]:"";pointInputs.push(input);pointRow.append(input);});box.append(pointRow,element("label",null,"调整后法向 [L, P, S]（可留空；输入后保留原数值）"));const normalRow=element("div","triplet"),normalInputs=[];["L","P","S"].forEach((axis,i)=>{const input=element("input");input.type="number";input.step="any";input.placeholder=axis;input.setAttribute("aria-label",label(l)+"调整后"+axis+"法向");input.value=finiteTriplet(r.adjusted_normal_lps)?r.adjusted_normal_lps[i]:"";normalInputs.push(input);normalRow.append(input);});box.append(normalRow);const error=element("div","validation");box.append(error);const update=()=>{const point=pointInputs.every(x=>x.value.trim()!=="")?pointInputs.map(x=>Number(x.value)):null;const normal=normalInputs.every(x=>x.value.trim()==="")?null:normalInputs.every(x=>x.value.trim()!=="")?normalInputs.map(x=>Number(x.value)):"incomplete";const valid=finiteTriplet(point)&&(normal===null||(finiteTriplet(normal)&&Math.hypot(...normal)>1e-8));error.textContent=valid?"调整仅写入审核记录；需在 CT 中确认后由后续流程采用。":"请填写三个有限坐标；法向需全部留空或填写三个有限数且不能为零。未完成的调整导出为待处理。";decisionRecord(c,l,{adjusted_point_lps_mm:point,adjusted_normal_lps:normal});};[...pointInputs,...normalInputs].forEach(input=>input.addEventListener("change",update));error.textContent=validAdjustment(r)?"调整仅写入审核记录；需在 CT 中确认后由后续流程采用。":"调整尚未完成，当前不会计为已处理。";return box;}
function renderImage(c,l){$("viewer-title").textContent=l?label(l)+" · 切片复核":"切片复核图";const wrap=$("image-wrap");wrap.replaceChildren();if(!l){wrap.append(element("p","muted","请选择候选。"));$("image-caption").textContent="";return;}if(!l.overlay_url){wrap.append(element("p","muted","该候选的复核图尚未生成。"));}else{const img=element("img");img.src=l.overlay_url;img.alt=c.case+" "+label(l)+" 切片叠加图";img.tabIndex=0;img.setAttribute("role","button");img.setAttribute("aria-label","放大切片叠加图");img.addEventListener("click",()=>openImage(img.src,img.alt));img.addEventListener("keydown",event=>{if(event.key==="Enter"||event.key===" "){event.preventDefault();openImage(img.src,img.alt);}});img.addEventListener("error",()=>{wrap.replaceChildren(element("p","muted","图像未能加载，请确认 HTML 与病例图像目录仍在原来的相对位置。"));});wrap.append(img);}$("image-caption").textContent=`${c.case} · ${l.id} · 原始候选 ${formatVector(l.proposal.point_lps_mm)}。审核记录不会修改图上的候选位置。`;}
function renderCoarseSummary(c){const prior=c.coarse_localization;const adjustment=c.coarse_adjustment;const box=$("coarse-summary");if(!prior){box.textContent="";return;}const refs=prior.accepted_references??[];const people=new Set(refs.map(r=>r.patient_id)).size;const active=Object.values(prior.landmarks??{}).filter(p=>p.status==="search_prior").length;const display=Object.values(prior.landmarks??{}).filter(p=>p.status==="display_only").length;const frame=adjustment?.unified_coordinate_system||"UAS";box.textContent=active?`本例采用 ${refs.length} 组扫描、${people} 位独立患者的粗定位参考，支持 ${active} 个点的搜索或对照；统一坐标 ${frame}，精调由本例 CT 完成。`:(display?`本例 ${display} 个粗定位点仅供显示，继续使用本例 CT 定位。`:"本例粗定位不可用，继续使用本例 CT 定位。");box.textContent+=" 粗定位参考接受与正式解剖审核分别记录。";}
function renderCaseDetail(c){const container=$("case-detail");container.replaceChildren();const notes=listStrings(c.notes);if(notes.length){const ul=element("ul");notes.forEach(n=>ul.append(element("li",null,n)));container.append(ul);}const pre=element("pre","mono");pre.textContent=JSON.stringify({coarse_localization:c.coarse_localization,coarse_adjustment:c.coarse_adjustment,review_queue:c.review_queue,anatomy_frame:c.anatomy_frame,parameters:c.parameters,source_file:c.source_file,source_sha256:c.source_sha256},null,2);container.append(pre);}
async function copyText(value){try{if(navigator.clipboard&&window.isSecureContext){await navigator.clipboard.writeText(value);}else{const area=element("textarea");area.value=value;area.style.position="fixed";area.style.opacity="0";document.body.append(area);area.select();const success=document.execCommand("copy");area.remove();if(!success)throw Error("copy unavailable");}toast("坐标已复制（LPS，mm）");}catch(error){toast("浏览器未允许复制，请从坐标或证据栏选取文字。 ");}}
function openImage(src,title){previousFocus=document.activeElement;$("large-image").src=src;$("large-image").alt=title;$("lightbox-title").textContent=title;$("lightbox-image").classList.remove("actual");$("lightbox").hidden=false;document.body.style.overflow="hidden";$("close-lightbox").focus();}
function closeImage(){$("lightbox").hidden=true;document.body.style.overflow="";if(previousFocus)previousFocus.focus();}
$("close-lightbox").addEventListener("click",closeImage);$("zoom-fit").addEventListener("click",()=>$("lightbox-image").classList.remove("actual"));$("zoom-actual").addEventListener("click",()=>$("lightbox-image").classList.add("actual"));document.addEventListener("keydown",event=>{if($("lightbox").hidden)return;if(event.key==="Escape")closeImage();if(event.key==="Tab"){const buttons=[$("zoom-fit"),$("zoom-actual"),$("close-lightbox")],index=buttons.indexOf(document.activeElement);event.preventDefault();buttons[(index+(event.shiftKey?2:1))%3].focus();}});
function exportReview(returnData=false){const invalid=[];const output={schema_version:"1.0",artifact_type:"landmark_review_decisions",coordinate_system:"LPS",unit:"mm",reviewer:$("reviewer").value.trim()||null,exported_at:new Date().toISOString(),proposal_bundle_sha256:DATA.proposal_bundle_sha256,scope:"Review records only. No proposal statuses, CFD geometry, planes or segmentation have been modified.",cases:DATA.cases.map(c=>({case:c.case,source_file:c.source_file,source_sha256:c.source_sha256,original_case_status:c.status,decisions:c.landmarks.map(l=>{const r=getRecord(c,l);const decision=safeDecision(r);if(r.decision==="adjust"&&decision==="pending")invalid.push(c.case+" / "+l.id);return {landmark_id:l.id,label_zh:label(l),label_en:englishLabel(l),proposal_sha256:l.proposal_sha256,original_status:l.proposal.status,original_point_lps_mm:l.proposal.point_lps_mm??null,original_normal_lps:l.proposal.normal_lps??null,decision,adjusted_point_lps_mm:decision==="adjust"?r.adjusted_point_lps_mm:null,adjusted_normal_lps:decision==="adjust"?(r.adjusted_normal_lps??null):null,note:typeof r.note==="string"?r.note:"",updated_at:r.updated_at||null,...(r.decision==="adjust"&&decision==="pending"?{incomplete_adjustment:{point_lps_mm:r.adjusted_point_lps_mm??null,normal_lps:r.adjusted_normal_lps??null}}:{})};})}))};if(returnData===true)return output;const blob=new Blob([JSON.stringify(output,null,2)+"\n"],{type:"application/json;charset=utf-8"});const url=URL.createObjectURL(blob),a=element("a");a.href=url;a.download="review_decisions.json";document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);toast(invalid.length?`已导出；${invalid.length} 项未完成调整保留为待处理。`:"审核记录已导出；原始候选和 CFD 几何未改变。");}
function inspectImportedReview(data){if(!data||data.artifact_type!=="landmark_review_decisions"||data.schema_version!=="1.0"||data.coordinate_system!=="LPS"||data.unit!=="mm"||!Array.isArray(data.cases))throw Error("文件不是本工具的 LPS/mm 审核记录。");const accepted=[],skipped=[],seen=new Set();for(const importedCase of data.cases){if(!importedCase||typeof importedCase!=="object")continue;const c=DATA.cases.find(x=>x.case===importedCase.case);const incoming=Array.isArray(importedCase.decisions)?importedCase.decisions:[];if(!c||c.source_sha256!==importedCase.source_sha256){incoming.forEach(d=>skipped.push({case:importedCase.case,id:d?.landmark_id,reason:"病例或源文件哈希不匹配"}));continue;}for(const d of incoming){if(!d||typeof d!=="object"){skipped.push({case:c.case,reason:"记录格式无效"});continue;}const l=c.landmarks.find(x=>x.id===d.landmark_id),key=c.case+":"+String(d.landmark_id);let reason="";if(seen.has(key))reason="文件内出现重复点位";else if(!l||l.proposal_sha256!==d.proposal_sha256)reason="候选哈希不匹配";else if(JSON.stringify(l.proposal.point_lps_mm??null)!==JSON.stringify(d.original_point_lps_mm??null)||JSON.stringify(l.proposal.normal_lps??null)!==JSON.stringify(d.original_normal_lps??null)||l.proposal.status!==d.original_status)reason="原始候选坐标、法向或状态不匹配";else if(!VALID_DECISIONS.has(d.decision))reason="审核决定无效";else if(d.decision==="adjust"&&!validAdjustment(d))reason="调整坐标无效";else if(d.decision==="accept"&&(!finiteTriplet(l.proposal.point_lps_mm)||l.proposal.status==="unavailable"))reason="无法接受未定位的候选";if(reason){skipped.push({case:c.case,id:d.landmark_id,reason});continue;}seen.add(key);accepted.push({c,l,record:{decision:d.decision,note:typeof d.note==="string"?d.note:"",updated_at:typeof d.updated_at==="string"&&Number.isFinite(Date.parse(d.updated_at))?d.updated_at:null,adjusted_point_lps_mm:d.decision==="adjust"?d.adjusted_point_lps_mm:null,adjusted_normal_lps:d.decision==="adjust"?(d.adjusted_normal_lps??null):null,imported_at:new Date().toISOString()}});}}return {accepted,skipped,reviewer:typeof data.reviewer==="string"?data.reviewer:""};}
$("import").addEventListener("click",()=>{$("import-file").value="";$("import-file").click();});
$("import-file").addEventListener("change",async()=>{const file=$("import-file").files[0];if(!file)return;try{if(file.size>10*1024*1024)throw Error("文件大于 10 MB，请确认选择了审核 JSON。");pendingImport=inspectImportedReview(JSON.parse(await file.text()));const current=pendingImport.accepted.filter(x=>safeDecision(getRecord(x.c,x.l))!=="pending").length;const reasons=[...new Set(pendingImport.skipped.map(x=>x.reason))].join("、");$("import-summary").textContent=`文件中 ${pendingImport.accepted.length} 项与当前候选完全匹配，其中 ${current} 项已有本地审核。${pendingImport.skipped.length} 项已跳过${reasons?"（"+reasons+"）":""}。默认仅补充待处理项；源文件哈希、候选哈希及原坐标均需匹配。`;$("apply-import").disabled=pendingImport.accepted.length===0;$("import-overwrite").checked=false;$("import-preview").hidden=false;}catch(error){pendingImport=null;$("import-preview").hidden=true;toast("未导入："+error.message);}});
$("apply-import").addEventListener("click",()=>{if(!pendingImport)return;const overwrite=$("import-overwrite").checked;let imported=0;for(const item of pendingImport.accepted){if(!overwrite&&safeDecision(getRecord(item.c,item.l))!=="pending")continue;records[recordKey(item.c,item.l)]=item.record;imported++;}if(!$("reviewer").value&&pendingImport.reviewer)$("reviewer").value=pendingImport.reviewer;save();pendingImport=null;$("import-preview").hidden=true;render();toast(`已导入 ${imported} 项审核记录；候选状态与 CFD 均未改动。`);});
$("cancel-import").addEventListener("click",()=>{pendingImport=null;$("import-preview").hidden=true;});
$("export").addEventListener("click",exportReview);$("filter").addEventListener("change",render);$("point-search").addEventListener("input",render);$("priority").addEventListener("change",render);$("reviewer").addEventListener("change",save);if(DATA.cases.length)activeCase=DATA.cases.reduce((best,c,i)=>c.landmarks.filter(attention).length>DATA.cases[best].landmarks.filter(attention).length?i:best,0);render();
</script></body></html>
'''


def build_review(base_dir, output=None, cases=None):
    base_dir = Path(base_dir).resolve()
    output = Path(output).resolve() if output else base_dir / "index.html"
    if cases:
        sources = []
        for case_id in cases:
            source = (base_dir / case_id / "landmarks.json").resolve()
            if not source.is_relative_to(base_dir):
                raise ValueError("Case path must remain within the input directory")
            if not source.is_file():
                raise FileNotFoundError(source)
            sources.append(source)
    else:
        sources = list(base_dir.glob("*/landmarks.json"))
        rank = {name: i for i, name in enumerate(PREFERRED_CASE_ORDER)}
        sources.sort(key=lambda p: (rank.get(p.parent.name, 999), p.parent.name))
    if not sources:
        raise FileNotFoundError(f"No case landmarks.json found under {base_dir}")
    data = [read_case(source, output.parent) for source in sources]
    ids = [item["case"] for item in data]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate case identifiers would make review records ambiguous")
    bundle_hash = sha256_json([{ "case": c["case"], "source_sha256": c["source_sha256"]}
                              for c in data])
    payload = {
        "schema_version": "1.0", "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "workspace_key": hashlib.sha256(str(base_dir).encode("utf-8")).hexdigest()[:20],
        "proposal_bundle_sha256": bundle_hash, "cases": data,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(HTML_HEAD + script_json(payload) + HTML_TAIL, encoding="utf-8")
    return {"html": str(output), "cases": len(data),
            "landmarks": sum(len(c["landmarks"]) for c in data),
            "missing_overlays": sum(l["overlay_missing"] for c in data for l in c["landmarks"]),
            "proposal_bundle_sha256": bundle_hash}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-dir", type=Path,
                        default=Path(__file__).resolve().parents[1] / "06_auto_landmarks")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--cases", nargs="+", help="Optional case directory names")
    args = parser.parse_args()
    summary = build_review(args.base_dir, args.output, args.cases)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
