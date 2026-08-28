"""Atour · 亚朵酒店全国比价工具。"""

import json
import os
import re
import uuid
from datetime import date, timedelta
from typing import Any

import sys
import traceback

import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components

try:
    from pypinyin import lazy_pinyin, Style
except Exception:  # 拼音库缺失时回退到按首字字符排序
    lazy_pinyin = None
    Style = None

from services.atour_api import ATOUR_TOKEN, AtourAPIError, fetch_atour_prices, get_atour_cities


st.set_page_config(page_title="Atour 亚朵比价", page_icon="🏨", layout="wide", initial_sidebar_state="collapsed")

# 全局压缩页面空白
st.html("""
<style>
.stApp, body, .stApp > header { background:#ffffff !important; }
/* 隐藏 Streamlit 顶部 Deploy 栏（Running / Deploy / 菜单），让首屏内容贴顶 */
header[data-testid="stHeader"], .stApp > header { display:none !important; }
/* 隐藏右下角 Streamlit Cloud 悬浮头像/管理菜单（仅云端部署时出现） */
#MainMenu, [data-testid="stStatusWidget"], [data-testid="stDecoration"],
div[data-testid="stBottom"] > div > div,
.stApp [data-testid="stToolbarActions"] { display:none !important; }
div.stApp > div > div[data-testid="stFloatingMenuContainer"] { display:none !important; }
.block-container{padding-top:0.5rem !important;padding-bottom:0 !important;
  padding-left:0 !important;padding-right:0 !important;max-width:100% !important;
  background:#ffffff}
/* 收紧垂直间隙，让下方空间留给地图+列表 */
[data-testid="stVerticalBlock"]{gap:0.3rem !important}
/* 防止页面整体滚动（地图/列表已撑到视口底，避免内容溢出产生页面滚动条） */
html, body, .stApp { overflow:hidden !important; height:100% !important; }
/* 主区（包含地图/列表的 stHorizontalBlock）占满视口剩余空间 */
[data-testid="stHorizontalBlock"]:has(> [data-testid="column"] [data-testid="stIFrame"]) {
  align-items:stretch !important;
  gap:0 !important;            /* 地图与列表两列去间隙，无缝占满整行宽度 */
}
[data-testid="stHorizontalBlock"]:has(> [data-testid="column"] [data-testid="stIFrame"]) > [data-testid="column"]{
  height:100% !important;
  padding-left:0 !important;   /* 去掉列内边距，避免地图/列表左右露出白边 */
  padding-right:0 !important;
}
h1[data-testid="stHeading"]{display:none}
/* 让 widget label 字体加重、字距收紧，与品牌行 lbl 风格呼应 */
[data-testid="stWidgetLabel"] p{font-weight:600;letter-spacing:.3px;text-transform:none}
/* 主按钮（type="primary"）统一蓝色主题 */
button[kind="primary"], button[data-testid="baseButton-primary"]{
  background:#1e6fff !important;
  color:#fff !important;
  border-color:#1e6fff !important;
}
button[kind="primary"]:hover, button[data-testid="baseButton-primary"]:hover{
  background:#1669e6 !important;
  border-color:#1669e6 !important;
}
</style>
""")

PRICE_COLUMNS = ["铂金会员价"]

# 排序候选
_SORT_FIELDS = ["铂金会员价", "开业时间"]
_SORT_OPTIONS = [f"{f} {d}" for f in _SORT_FIELDS for d in ("升序", "降序")]

# 酒店类型筛选候选
HOTEL_TYPE_OPTIONS = ["亚朵", "亚朵V3.6", "亚朵S", "亚朵X", "亚朵轻居", "亚朵见野"]


def _open_date_sort_key(value: object):
    if not isinstance(value, str):
        return None
    m = re.search(r"(\d{4})年(?:(\d{1,2})月)?", value)
    if not m:
        return None
    return int(m.group(1)) * 12 + int(m.group(2) or 0)


def _pinyin_key(name: str) -> str:
    if lazy_pinyin is not None and name:
        return "".join(lazy_pinyin(name))
    return name


# 城市/省份列表
FALLBACK_CITIES = ["北京", "上海", "广州", "深圳", "杭州", "成都", "南京", "武汉", "西安", "重庆"]
FALLBACK_PROVINCES = ["北京", "上海", "广东", "浙江", "江苏", "四川", "湖北", "陕西", "重庆", "福建", "山东", "湖南"]

try:
    _PROVINCE_MAP = get_atour_cities()
except Exception:
    _PROVINCE_MAP = None

if _PROVINCE_MAP:
    ALL_CITIES = sorted({c for cs in _PROVINCE_MAP.values() for c in cs}, key=_pinyin_key)
    PROVINCES = sorted(_PROVINCE_MAP.keys(), key=_pinyin_key)
else:
    ALL_CITIES = sorted(FALLBACK_CITIES, key=_pinyin_key)
    PROVINCES = sorted(FALLBACK_PROVINCES, key=_pinyin_key)


def _pinyin_initial(name: str) -> str:
    if lazy_pinyin is not None and name:
        letters = lazy_pinyin(name, style=Style.FIRST_LETTER)
        if letters:
            return letters[0].upper()
    return (name[0].upper() if name else "?")


# 分隔符前缀
_DIVIDER_PREFIX = "── "


def _build_grouped_options(names: list[str]) -> list[str]:
    initials = sorted({_pinyin_initial(n) for n in names})
    opts: list[str] = []
    for ini in initials:
        opts.append(f"{_DIVIDER_PREFIX}{ini} ──")
        grp = sorted([n for n in names if _pinyin_initial(n) == ini], key=_pinyin_key)
        opts.extend(grp)
    return opts


def _first_real_index(options: list[str]) -> int:
    for i, o in enumerate(options):
        if not o.startswith(_DIVIDER_PREFIX):
            return i
    return 0


CITY_OPTIONS = _build_grouped_options(ALL_CITIES) if ALL_CITIES else []
PROVINCE_OPTIONS = _build_grouped_options(PROVINCES) if PROVINCES else []


def format_price(value: object) -> str:
    return "—" if pd.isna(value) else f"¥{float(value):,.2f}"


def _city_of(value: object) -> str:
    return str(value).split("/")[0] if isinstance(value, str) and value else ""


def _district_of(value: object) -> str:
    return str(value).split("/")[1] if isinstance(value, str) and "/" in value else ""


def _open_date_short(value: object) -> str:
    if not isinstance(value, str):
        return "—"
    m = re.search(r"(\d{4})年(?:(\d{1,2})月)?", value)
    if not m:
        return "—"
    return f"{m.group(1)}.{m.group(2)}" if m.group(2) else m.group(1)


# 地图（Leaflet + 高德 Amap 瓦片）
_LEAFLET_AMAP_SHELL = """<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<link rel="stylesheet" href="https://cdn.bootcdn.net/ajax/libs/leaflet/1.9.4/leaflet.min.css">
<style>
html,body{margin:0;padding:0;height:100%}
#map{width:100%;height:100%;background:#ffffff}
/* 地图边缘渐变：四边向内渐隐到纯白页面底色，范围 14% 让过渡更柔和 */
.map-fade{position:absolute;inset:0;pointer-events:none;z-index:1000;
  background:
    linear-gradient(to bottom, rgba(255,255,255,.95) 0%, transparent 14%),
    linear-gradient(to top, rgba(255,255,255,.95) 0%, transparent 14%),
    linear-gradient(to right, rgba(255,255,255,.95) 0%, transparent 14%),
    linear-gradient(to left, rgba(255,255,255,.95) 0%, transparent 14%)}
/* iOS Apple Maps 风格调色：高德 style=8 瓦片通过 CSS filter 转成 iOS 观感
   - sepia(.06)   米白暖底（iOS 底色偏米白而非纯灰白）
   - saturate(1.45) 大幅增强饱和度 → 绿地/公园/山丘显著变绿、水域更蓝
   - brightness(1.05) 提亮底
   - contrast(.96)  柔和过渡 */
.leaflet-tile-pane .leaflet-tile{
  filter:sepia(.06) saturate(1.45) brightness(1.05) contrast(.96)}
/* 价格气泡（三行：类型 / 价格 / 开业时间）。锚点由 Leaflet iconAnchor 控制居中 */
.price-bubble-anchor{background:transparent!important;border:none!important}
.price-bubble{display:inline-block;cursor:pointer;user-select:none;
  font-family:'Inter','PingFang SC','Microsoft YaHei',sans-serif;
  filter:drop-shadow(0 2px 5px rgba(0,0,0,.22));position:relative;overflow:hidden;border-radius:10px}
.price-bubble .pb{
  background:#1e6fff;color:#fff;border-radius:10px;
  padding:5px 12px 6px;min-width:68px;
  display:flex;flex-direction:column;align-items:center;line-height:1.25;
  border:1px solid #1e6fff;box-sizing:border-box;transition:transform .15s;
  white-space:nowrap;text-align:center;position:relative;overflow:hidden}
.price-bubble .pb .t{font-size:10px;font-weight:500;opacity:.82;letter-spacing:.3px}
.price-bubble .pb .p{font-size:15px;font-weight:700;margin-top:1px}
.price-bubble .pb .d{font-size:9.5px;font-weight:500;opacity:.75;margin-top:1px}
.price-bubble.full .pb{background:#fff;color:#1e6fff;border:1.5px solid #1e6fff}
.price-bubble:hover .pb{transform:scale(1.08)}
/* 波纹动画 */
@keyframes ripple-animation{
  to{ transform:scale(4); opacity:0; }
}
.price-bubble .ripple{
  position:absolute;border-radius:50%;transform:scale(0);
  animation:ripple-animation .6s linear;
  background:rgba(255,255,255,.35);pointer-events:none;
}
/* iOS 风格控件：右下角缩放、淡白底 */
.leaflet-bottom.leaflet-right{margin:14px}
.leaflet-control-zoom{border:none!important;box-shadow:0 1px 4px rgba(0,0,0,.18);border-radius:9px;overflow:hidden}
.leaflet-control-zoom a{background:#fff!important;color:#1a1a1a!important;border:none!important;
  width:38px;height:38px;line-height:38px;font-size:20px;font-weight:500!important}
.leaflet-control-zoom a:hover{background:#f3f3f3!important}
.leaflet-control-zoom a:first-child{border-bottom:1px solid #e5e5e5!important}
.leaflet-control-attribution{background:rgba(255,255,255,.78);font-size:10px;
  padding:1px 6px;color:#888;border-radius:4px;margin:6px}
.leaflet-control-attribution a{color:#888;text-decoration:none}
</style>
</head><body>
<div id="map"></div>
<div class="map-fade"></div>
<script src="https://cdn.bootcdn.net/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>
<script>
window.__ATOUR_MAP_TOKEN = '@@TOKEN@@';
window.__INIT_POINTS__ = @@INIT_POINTS@@;
window.__INIT_FIT__ = @@INIT_FIT@@;

// GCJ-02 → WGS-84 转换（消除"中国地图偏移"，亚朵 API 返回 GCJ-02，瓦片也是 GCJ-02）
const PI=Math.PI, A=6378245.0, EE=0.00669342162296594323;
function outOfChina(lng,lat){return !(lng>73.66&&lng<135.05&&lat>3.86&&lat<53.55);}
function tLat(x,y){let r=-100+2*x+3*y+.2*y*y+.1*x*y+.2*Math.sqrt(Math.abs(x));
  r+=(20*Math.sin(6*x*PI)+20*Math.sin(2*x*PI))*2/3;
  r+=(20*Math.sin(y*PI)+40*Math.sin(y/3*PI))*2/3;
  r+=(160*Math.sin(y/12*PI)+320*Math.sin(y*PI/30))*2/3;return r;}
function tLng(x,y){let r=300+x+2*y+.1*x*x+.1*x*y+.1*Math.sqrt(Math.abs(x));
  r+=(20*Math.sin(6*x*PI)+20*Math.sin(2*x*PI))*2/3;
  r+=(20*Math.sin(x*PI)+40*Math.sin(x/3*PI))*2/3;
  r+=(150*Math.sin(x/12*PI)+300*Math.sin(x/30*PI))*2/3;return r;}
function gcjToWgs(lng,lat){
  if(outOfChina(lng,lat))return[lng,lat];
  let dLat=tLat(lng-105,lat-35),dLng=tLng(lng-105,lat-35);
  const rL=lat/180*PI;let m=Math.sin(rL);m=1-EE*m*m;const sm=Math.sqrt(m);
  dLat=(dLat*180)/((A*(1-EE))/(m*sm)*PI);
  dLng=(dLng*180)/(A/sm*Math.cos(rL)*PI);
  return[lng*2-(lng+dLng),lat*2-(lat+dLat)];
}

// 高德地图瓦片（GCJ-02 坐标系；style=8 标准浅色，接近 iOS Apple Maps 观感）
window.__tileLayer = L.tileLayer(
  'https://webrd0{s}.is.autonavi.com/appmaptile?lang=en&size=1&scale=1&style=8&x={x}&y={y}&z={z}',
  { subdomains:['1','2','3','4'], maxZoom:18, attribution:'© 高德地图' }
);

window.__atourMap = L.map('map', {
  center: [@@CENTER_LAT@@, @@CENTER_LNG@@],
  zoom: @@ZOOM@@,
  minZoom: 3,
  layers: [window.__tileLayer],
  zoomControl: false,
  attributionControl: true,
  fadeAnimation: false
});
L.control.zoom({ position:'bottomright' }).addTo(window.__atourMap);

// 点击地图空白处 → 取消聚焦，恢复全部气泡（与气泡点击的「再次点击恢复」保持一致）
window.__atourMap.on('click', function(){
  if (window.__focusedKey) window.__clearFocus();
});

window.__bubbles = {};
// 当前聚焦（选中）的酒店 key：列表行点击 / 气泡点击都会经 __focusHotel 设置；
// 增量更新（__setBubbles）后据此恢复「隐藏其他气泡」的焦点态，避免选中态被打断。
window.__focusedKey = null;
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){
  return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}

// 控制器调用的唯一入口：整体替换气泡集合。fit=true 时 fitBounds（仅当数量变化时由壳外控制）。
// 同时保存全量数据到 __allPoints，供取消聚焦（__clearFocus）时恢复全部气泡。
window.__setBubbles = function(points, fit) {
  window.__allPoints = points || [];
  Object.keys(window.__bubbles).forEach(function(k){
    try { window.__atourMap.removeLayer(window.__bubbles[k]); } catch(e){}
    delete window.__bubbles[k];
  });
  (points || []).forEach(function(p){
    const c = gcjToWgs(p.lng, p.lat);
    const html = '<div class="price-bubble' + (p.full ? ' full' : '') + '">' +
      '<div class="pb">' +
        '<div class="t">' + esc(p.t) + '</div>' +
        '<div class="p">' + esc(p.p) + '</div>' +
        '<div class="d">' + esc(p.d) + '</div>' +
      '</div></div>';
    const icon = L.divIcon({
      className: 'price-bubble-anchor',
      html: html,
      iconSize: [80, 50],
      iconAnchor: [40, 25]
    });
    const marker = L.marker([c[1], c[0]], { icon: icon, riseOnHover: true, keyboard: false });
    marker.on('click', function(e){
      // 波纹效果
      const bubbleEl = marker.getElement();
      if (bubbleEl) {
        const ripple = document.createElement('span');
        ripple.className = 'ripple';
        const rect = bubbleEl.getBoundingClientRect();
        const size = Math.max(rect.width, rect.height);
        ripple.style.width = ripple.style.height = size + 'px';
        ripple.style.left = ((e.originalEvent ? e.originalEvent.clientX : rect.left + rect.width/2) - rect.left - size/2) + 'px';
        ripple.style.top = ((e.originalEvent ? e.originalEvent.clientY : rect.top + rect.height/2) - rect.top - size/2) + 'px';
        bubbleEl.querySelector('.pb').appendChild(ripple);
        setTimeout(() => ripple.remove(), 600);
      }
      if (window.__focusedKey === p.key) {
        window.__clearFocus();
      } else {
        window.__focusedKey = p.key;
        window.__applyFocus();
      }
      try {
        const frames = window.parent.document.querySelectorAll('iframe');
        for (let i = 0; i < frames.length; i++) {
          const w = frames[i].contentWindow;
          if (w && w.__ATOUR_LIST) w.postMessage({type:'atour:focusBubble', key: p.key}, '*');
        }
      } catch(e) {}
    });
    marker.on('mousedown', function(e){ L.DomEvent.stopPropagation(e); });
    marker.addTo(window.__atourMap);
    window.__bubbles[p.key] = marker;
  });
  if (fit && !window.__focusedKey && points && points.length > 1) {
    const b = L.latLngBounds(points.map(function(p){
      const c = gcjToWgs(p.lng, p.lat);
      return [c[1], c[0]];
    }));
    window.__atourMap.fitBounds(b, { padding: [60, 60] });
  }
  // 重建后恢复焦点：若同步期间用户已选中某气泡/行，仅隐藏其他气泡（不重置缩放），
  // 避免「整体替换气泡」把选中态抹掉。
  window.__applyFocus();
};
// 仅隐藏非聚焦气泡（保留缩放/位置；供 __setBubbles 重建后恢复焦点用，不重新缩放）
window.__applyFocus = function() {
  if (!window.__focusedKey || !window.__atourMap) return;
  const k = window.__focusedKey;
  Object.keys(window.__bubbles).forEach(function(mk){
    const m = window.__bubbles[mk];
    if (!m) return;
    if (mk === k) { if (!window.__atourMap.hasLayer(m)) m.addTo(window.__atourMap); }
    else { if (window.__atourMap.hasLayer(m)) window.__atourMap.removeLayer(m); }
  });
};
// 列表行点击触发的焦点：隐藏其他气泡 + 缩放到该酒店周边 10km 范围
window.__focusHotel = function(key, lat, lng) {
  if (!window.__atourMap) return;
  window.__focusedKey = key;
  window.__applyFocus();
  // 缩放：以该酒店为中心 10km 范围（zoom 12 ≈ 10km 半径）
  if (lat != null && lng != null) {
    const c = gcjToWgs(Number(lng), Number(lat));
    window.__atourMap.setView([c[1], c[0]], 12, { animate: true, duration: 0.5 });
  }
};
// 取消聚焦：恢复全部气泡，保持当前缩放与位置（不 fitBounds、不重载）
window.__clearFocus = function() {
  if (!window.__atourMap) return;
  window.__focusedKey = null;
  window.__setBubbles(window.__allPoints, false);
};
// 列表筛选/排序联动：仅显示可见 key 对应的气泡，其余移除（不重置缩放/位置）。
window.__filterBubbles = function(keys) {
  if (!window.__atourMap) return;
  const set = (keys && keys.length) ? new Set(keys) : null;
  Object.keys(window.__bubbles).forEach(function(k){
    const m = window.__bubbles[k];
    if (!m) return;
    const visible = !set || set.has(k);
    if (visible) {
      if (!window.__atourMap.hasLayer(m)) m.addTo(window.__atourMap);
    } else {
      if (window.__atourMap.hasLayer(m)) window.__atourMap.removeLayer(m);
    }
  });
};
window.addEventListener('message', function(e){
  if (!e || !e.data) return;
  if (e.data.type === 'atour:focusHotel' && e.data.key) {
    window.__focusHotel(e.data.key, e.data.lat, e.data.lng);
  } else if (e.data.type === 'atour:clearFocus') {
    window.__clearFocus();
  } else if (e.data.type === 'atour:filterBubbles' && e.data.keys) {
    window.__filterBubbles(e.data.keys);
  }
});

// 壳内嵌初始数据：用于「重发壳」时一次性把当前数据写入，避免「壳/控制器」竞争导致气泡丢失。
try {
  if (window.__INIT_POINTS__ && window.__INIT_POINTS__.length) {
    window.__setBubbles(window.__INIT_POINTS__, !!window.__INIT_FIT__);
  }
} catch (e) { /* 地图未就绪时静默，控制器会兜底 */ }
</script></body></html>"""

# 地图（Apple Maps via MapKit JS）
_MAPKIT_SHELL = """<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<style>
html,body{margin:0;padding:0;height:100%}
#map{width:100%;height:100%;background:#ffffff}
/* 价格气泡（三行：类型/价格/开业时间）——与 iOS 视觉一致的深色胶囊 */
.price-bubble{display:inline-block;cursor:pointer;user-select:none;
  font-family:-apple-system,'SF Pro Text','PingFang SC','Microsoft YaHei',sans-serif;
  filter:drop-shadow(0 2px 5px rgba(0,0,0,.25))}
.price-bubble .pb{
  background:#1e6fff;color:#fff;border-radius:10px;
  padding:5px 12px 6px;min-width:68px;
  display:flex;flex-direction:column;align-items:center;line-height:1.25;
  border:1px solid #1e6fff;box-sizing:border-box;transition:transform .15s;
  white-space:nowrap;text-align:center;position:relative;overflow:hidden}
.price-bubble .pb .t{font-size:10px;font-weight:500;opacity:.82;letter-spacing:.3px}
.price-bubble .pb .p{font-size:15px;font-weight:700;margin-top:1px}
.price-bubble .pb .d{font-size:9.5px;font-weight:500;opacity:.75;margin-top:1px}
.price-bubble.full .pb{background:#fff;color:#1e6fff;border:1.5px solid #1e6fff}
.price-bubble:hover .pb{transform:scale(1.08)}
/* 波纹动画 */
@keyframes ripple-animation{
  to{ transform:scale(4); opacity:0; }
}
.price-bubble .ripple{
  position:absolute;border-radius:50%;transform:scale(0);
  animation:ripple-animation .6s linear;
  background:rgba(255,255,255,.35);pointer-events:none;
}
/* 地图边缘渐变：四边向内渐隐到纯白页面底色，范围 14% 让过渡更柔和 */
.map-fade{position:absolute;inset:0;pointer-events:none;z-index:1000;
  background:
    linear-gradient(to bottom, rgba(255,255,255,.95) 0%, transparent 14%),
    linear-gradient(to top, rgba(255,255,255,.95) 0%, transparent 14%),
    linear-gradient(to right, rgba(255,255,255,.95) 0%, transparent 14%),
    linear-gradient(to left, rgba(255,255,255,.95) 0%, transparent 14%)}
</style>
</head><body>
<div id="map"></div>
<div class="map-fade"></div>
<script src="https://cdn.apple-mapkit.com/mk/5.x.x/mapkit.core.js"></script>
<script>
window.__ATOUR_MAP_TOKEN = '@@TOKEN@@';
window.__INIT_POINTS__ = @@INIT_POINTS@@;
window.__INIT_FIT__ = @@INIT_FIT@@;
window.__atourMap = null;
window.__annotations = [];
// 当前聚焦（选中）的酒店 key：增量更新（__setBubbles）后据此恢复「隐藏其他气泡」的焦点态。
window.__focusedKey = null;

// GCJ-02 → WGS-84 转换（消除"中国地图偏移"；Apple 中国地图数据由高德提供）
const PI=Math.PI, A=6378245.0, EE=0.00669342162296594323;
function outOfChina(lng,lat){return !(lng>73.66&&lng<135.05&&lat>3.86&&lat<53.55);}
function tLat(x,y){let r=-100+2*x+3*y+.2*y*y+.1*x*y+.2*Math.sqrt(Math.abs(x));
  r+=(20*Math.sin(6*x*PI)+20*Math.sin(2*x*PI))*2/3;
  r+=(20*Math.sin(y*PI)+40*Math.sin(y/3*PI))*2/3;
  r+=(160*Math.sin(y/12*PI)+320*Math.sin(y*PI/30))*2/3;return r;}
function tLng(x,y){let r=300+x+2*y+.1*x*x+.1*x*y+.1*Math.sqrt(Math.abs(x));
  r+=(20*Math.sin(6*x*PI)+20*Math.sin(2*x*PI))*2/3;
  r+=(20*Math.sin(x*PI)+40*Math.sin(x/3*PI))*2/3;
  r+=(150*Math.sin(x/12*PI)+300*Math.sin(x/30*PI))*2/3;return r;}
function gcjToWgs(lng,lat){
  if(outOfChina(lng,lat))return[lng,lat];
  let dLat=tLat(lng-105,lat-35),dLng=tLng(lng-105,lat-35);
  const rL=lat/180*PI;let m=Math.sin(rL);m=1-EE*m*m;const sm=Math.sqrt(m);
  dLat=(dLat*180)/((A*(1-EE))/(m*sm)*PI);
  dLng=(dLng*180)/(A/sm*Math.cos(rL)*PI);
  return[lng*2-(lng+dLng),lat*2-(lat+dLat)];
}

// 初始化 MapKit JS（token 由后端环境变量 MAPKIT_TOKEN 注入）
mapkit.init({
  authorizationCallback: function(done){ done('@@MAPKIT_TOKEN@@'); },
  language: 'zh-CN'
});

// 自定义 Annotation：三行气泡（element 由 MapKit 自动定位到坐标）
class PriceAnnotation extends mapkit.Annotation {
  constructor(coordinate, opts) {
    super(coordinate, opts);
    this.pdata = opts.pdata || {};
  }
  get element() {
    const wrap = document.createElement('div');
    wrap.className = 'price-bubble' + (this.pdata.full ? ' full' : '');
    const pb = document.createElement('div'); pb.className = 'pb';
    const elT = document.createElement('div'); elT.className = 't'; elT.textContent = this.pdata.t;
    const elP = document.createElement('div'); elP.className = 'p'; elP.textContent = this.pdata.p;
    const elD = document.createElement('div'); elD.className = 'd'; elD.textContent = this.pdata.d;
    pb.appendChild(elT); pb.appendChild(elP); pb.appendChild(elD);
    wrap.appendChild(pb);
    // 点击气泡 → 通知列表 iframe 高亮对应行
    // 交互效果：单击气泡「隐去其他气泡、只保留当前」；再次点击同一气泡「恢复全部气泡」。
    wrap.addEventListener('click', function(e){
      // 波纹效果
      const ripple = document.createElement('span');
      ripple.className = 'ripple';
      const rect = wrap.getBoundingClientRect();
      const size = Math.max(rect.width, rect.height);
      ripple.style.width = ripple.style.height = size + 'px';
      ripple.style.left = (e.clientX - rect.left - size/2) + 'px';
      ripple.style.top = (e.clientY - rect.top - size/2) + 'px';
      wrap.querySelector('.pb').appendChild(ripple);
      setTimeout(() => ripple.remove(), 600);
      if (window.__focusedKey === this.pdata.key) {
        window.__clearFocus();
      } else {
        window.__focusedKey = this.pdata.key;
        window.__applyFocus();
      }
      try {
        const frames = window.parent.document.querySelectorAll('iframe');
        for (let i = 0; i < frames.length; i++) {
          const w = frames[i].contentWindow;
          if (w && w.__ATOUR_LIST) w.postMessage({type:'atour:focusBubble', key: this.pdata.key}, '*');
        }
      } catch(e) {}
    }.bind(this));
    return wrap;
  }
}

// 控制器调用的唯一入口：整体替换气泡集合；保存全量数据到 __allPoints 供取消聚焦恢复
window.__setBubbles = function(points, fit) {
  if (!window.__atourMap) return;
  window.__allPoints = points || [];
  if (window.__annotations.length) { window.__atourMap.removeAnnotations(window.__annotations); }
  window.__annotations = [];
  (points || []).forEach(function(p){
    const c = gcjToWgs(p.lng, p.lat);
    const ann = new PriceAnnotation(new mapkit.Coordinate(c[1], c[0]), { pdata: p });
    window.__atourMap.addAnnotation(ann);
    window.__annotations.push(ann);
  });
  if (fit && !window.__focusedKey && points && points.length > 1) {
    window.__atourMap.showItems(window.__annotations, { padding: new mapkit.Padding(60, 60, 60, 60) });
  }
  // 重建后恢复焦点：若同步期间用户已选中某气泡/行，仅隐藏其他气泡（不重置缩放），避免选中态被打断。
  window.__applyFocus();
};
// 仅隐藏非聚焦 annotation（保留缩放/位置；供 __setBubbles 重建后恢复焦点用，不重新缩放）
window.__applyFocus = function() {
  if (!window.__focusedKey || !window.__atourMap) return;
  const k = window.__focusedKey;
  const keep = [];
  window.__annotations.forEach(function(ann){
    if (ann.pdata && ann.pdata.key === k) keep.push(ann);
  });
  if (window.__annotations.length) window.__atourMap.removeAnnotations(window.__annotations);
  window.__annotations = [];
  keep.forEach(function(ann){
    window.__atourMap.addAnnotation(ann);
    window.__annotations.push(ann);
  });
};
// 列表行点击触发的焦点：隐藏其他 annotation + setRegion 到该酒店周边 10km 范围
window.__focusHotel = function(key, lat, lng) {
  if (!window.__atourMap) return;
  window.__focusedKey = key;
  window.__applyFocus();
  // 缩放：以该酒店为中心 10km 范围（span 0.18° ≈ 20km 直径 ≈ 10km 半径）
  if (lat != null && lng != null) {
    const c = gcjToWgs(Number(lng), Number(lat));
    window.__atourMap.setRegion(new mapkit.CoordinateRegion(
      new mapkit.Coordinate(c[1], c[0]),
      new mapkit.CoordinateSpan(0.18, 0.18)
    ), { animate: true });
  }
};
// 取消聚焦：恢复全部气泡，保持当前缩放与位置（不 showItems、不重载）
window.__clearFocus = function() {
  if (!window.__atourMap) return;
  window.__focusedKey = null;
  window.__setBubbles(window.__allPoints, false);
};
// 列表筛选/排序联动：仅显示可见 key 对应的气泡，其余移除（不重置缩放/位置）。
window.__filterBubbles = function(keys) {
  if (!window.__atourMap) return;
  const set = (keys && keys.length) ? new Set(keys) : null;
  window.__annotations.forEach(function(ann){
    const k = ann.pdata && ann.pdata.key;
    const visible = !set || set.has(k);
    if (visible) {
      if (window.__atourMap.annotations.indexOf(ann) < 0) window.__atourMap.addAnnotation(ann);
    } else {
      if (window.__atourMap.annotations.indexOf(ann) >= 0) window.__atourMap.removeAnnotation(ann);
    }
  });
};
window.addEventListener('message', function(e){
  if (!e || !e.data) return;
  if (e.data.type === 'atour:focusHotel' && e.data.key) {
    window.__focusHotel(e.data.key, e.data.lat, e.data.lng);
  } else if (e.data.type === 'atour:clearFocus') {
    window.__clearFocus();
  } else if (e.data.type === 'atour:filterBubbles' && e.data.keys) {
    window.__filterBubbles(e.data.keys);
  }
});

// 初始化完成后创建地图（configuration-change 事件在 mapkit.init 成功后触发）
mapkit.addEventListener('configuration-change', function(){
  if (window.__atourMap) return;
  window.__atourMap = new mapkit.Map('map', {
    center: new mapkit.Coordinate(@@CENTER_LAT@@, @@CENTER_LNG@@),
    zoom: @@ZOOM@@,
    minZoom: 3,
    showsCompass: mapkit.CompassVisibility.Hidden,
    showsZoomControl: false,
    showsScale: false,
    showsMapTypeControl: false,
    colorScheme: mapkit.Map.ColorSchemes.Light
  });
  // 点击地图空白处 → 取消聚焦，恢复全部气泡（Annotation 元素点击不触发 map click）
  window.__atourMap.addEventListener('click', function(){
    if (window.__focusedKey) window.__clearFocus();
  });
  try {
    if (window.__INIT_POINTS__ && window.__INIT_POINTS__.length) {
      window.__setBubbles(window.__INIT_POINTS__, !!window.__INIT_FIT__);
    }
  } catch (e) { /* 控制器会兜底 */ }
});
</script></body></html>"""

def _points_from(records: list[dict]) -> list[dict]:
    points = []
    for i, r in enumerate(records):
        lat, lng = r.get("latitude"), r.get("longitude")
        if lat is None or lng is None:
            continue
        full = r.get("是否有房") == "满房"
        price = r.get("铂金会员价")
        if full:
            price_text = "满房"
        elif price:
            price_text = f"¥{price:,.0f}"
        else:
            price_text = "—"
        type_text = str(r.get("酒店类型") or "") or "—"
        open_date = str(r.get("开业时间") or "") or "—"
        if open_date.endswith("开业"):
            open_date = open_date[:-2]  # '2026年7月开业' -> '2026年7月'
        points.append({
            "lat": lat, "lng": lng, "full": full,
            "t": type_text,
            "p": price_text,
            "d": open_date,
            "key": f"h{r.get('chainId') or i}",
        })
    return points


def _mapkit_token() -> str:
    return os.environ.get("MAPKIT_TOKEN", "").strip()


def _build_map_shell(
    token: str,
    center_lat: float,
    center_lng: float,
    zoom: int = 11,
    init_points: list[dict] | None = None,
    init_fit: bool = False,
) -> str:
    pts_json = json.dumps(init_points or [], ensure_ascii=False)
    mk_token = _mapkit_token()
    if mk_token:
        tpl = _MAPKIT_SHELL
    else:
        tpl = _LEAFLET_AMAP_SHELL
    return (
        tpl.replace("@@TOKEN@@", token)
        .replace("@@MAPKIT_TOKEN@@", mk_token)
        .replace("@@CENTER_LAT@@", f"{center_lat:.6f}")
        .replace("@@CENTER_LNG@@", f"{center_lng:.6f}")
        .replace("@@ZOOM@@", str(zoom))
        .replace("@@INIT_POINTS@@", pts_json)
        .replace("@@INIT_FIT@@", "true" if init_fit else "false")
    )


def _build_controller_js(token: str, points: list[dict], fit: bool = False) -> str:
    payload = json.dumps(points, ensure_ascii=False)
    fit_flag = "true" if fit else "false"
    return """<script>
(function(){
  const token = '%s';
  const points = %s;
  const fit = %s;
  let attempts = 0;
  function tryUpdate() {
    attempts++;
    const frames = parent.document.querySelectorAll('iframe');
    for (let i = 0; i < frames.length; i++) {
      const f = frames[i];
      if (f.srcdoc && f.srcdoc.indexOf(token) > -1) {
        const w = f.contentWindow;
        if (w && typeof w.__setBubbles === 'function') {
          w.__setBubbles(points, fit);
          return;
        }
      }
    }
    if (attempts < 100) setTimeout(tryUpdate, 50);
  }
  tryUpdate();
})();
</script>""" % (token, payload, fit_flag)


_CHINA_CENTER = (34.0, 108.5)
_DEFAULT_MAP_ZOOM = 4


def _emit_map(records: list[dict], fit: bool = False, center: tuple | None = None, zoom: int = _DEFAULT_MAP_ZOOM) -> None:
    token = st.session_state.get("_map_token")
    if not token:
        return
    n = len(_points_from(records))
    last_fit = st.session_state.get("_map_fit_count", -1)
    fit_now = bool(fit) and n > 1 and n != last_fit
    if fit_now:
        st.session_state["_map_fit_count"] = n

    if st.session_state.get("_map_emitted"):
        # 同一次运行已渲染过地图：只推气泡（壳-控制器架构；控制器内自带轮询）。
        components.html(_build_controller_js(token, _points_from(records), fit_now), height=1)
        return

    cached = st.session_state.get("_map_html")
    if cached:
        # 跨 run 重发（如新查询首帧 / 筛选后）：构造「暖壳」——把当前数据嵌入壳内一次性注入，
        # 避免「壳加载未完成 vs 控制器先跑」的 race（旧实现下气泡会在 rerun 后消失）。
        points = _points_from(records)
        if points:
            clat = sum(p["lat"] for p in points) / len(points)
            clng = sum(p["lng"] for p in points) / len(points)
            czoom = 11
        else:
            clat, clng = _CHINA_CENTER
            czoom = _DEFAULT_MAP_ZOOM
        warm = _build_map_shell(token, clat, clng, zoom=czoom,
                                 init_points=points, init_fit=fit_now)
        components.html(warm, height=720)
        st.session_state["_map_html"] = warm
        st.session_state["_map_emitted"] = True
        return

    points = _points_from(records)
    if not points:
        # 无点但壳尚未创建（搜索初期）：用默认中心/缩放立即建出空壳，
        # 保证搜索期间左列就是地图（可缩放/平移），数据到达后由控制器注入气泡并 fit。
        clat, clng = center if center else _CHINA_CENTER
        shell = _build_map_shell(token, clat, clng, zoom=zoom)
        st.session_state["_map_html"] = shell
        st.session_state["_map_emitted"] = True
        components.html(shell, height=720)
        return
    center_lat = sum(p["lat"] for p in points) / len(points)
    center_lng = sum(p["lng"] for p in points) / len(points)
    shell = _build_map_shell(token, center_lat, center_lng)
    st.session_state["_map_html"] = shell
    st.session_state["_map_emitted"] = True
    components.html(shell, height=720)
    components.html(_build_controller_js(token, points, fit_now), height=1)


# 列表样式
_THIRDGINGER_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,400;0,500;0,600;1,400;1,500;1,600&family=Inter:wght@400;500;600;700&display=swap');
.tg-list{font-family:'Inter','PingFang SC','Microsoft YaHei',sans-serif;background:#fff;color:#111;
  padding:6px 20px 24px;border-left:1px solid #ececec;height:100%;box-sizing:border-box;
  display:flex;flex-direction:column;overflow:hidden;overflow-x:hidden}
.tg-meta-top{font-size:9px;letter-spacing:1.5px;color:#999;font-weight:600;text-transform:uppercase;
  margin-top:14px;margin-bottom:2px;flex-shrink:0}
.tg-title{font-family:'Inter',sans-serif;font-weight:700;font-size:22px;line-height:1;letter-spacing:-.6px;
  color:#0a0a0a;margin:0 0 16px;text-transform:uppercase;flex-shrink:0}
/* 行区滚动：列表总高度 = 地图高度（iframe 720px），标题/底部固定，中间行区仅纵向滚动（无横向滚动条） */
.tg-list-body{flex:1 1 auto;overflow-y:auto;overflow-x:hidden;border-top:1px solid #ececec;min-height:0}
.tg-list-body::-webkit-scrollbar{width:4px}
.tg-list-body::-webkit-scrollbar-thumb{background:#e0e0e0;border-radius:2px}
.tg-list-body::-webkit-scrollbar-track{background:transparent}
.tg-foot{flex-shrink:0}
/* 搜索框：位于筛选区上方，细极简风格，聚焦时边框加深 + 轻微阴影留白 */
.tg-search{position:relative;display:flex;align-items:center;margin:2px 0 10px;flex-shrink:0;overflow:hidden;border-radius:8px}
.tg-search-icon{position:absolute;left:10px;top:50%;transform:translateY(-50%);width:14px;height:14px;color:#aaa;pointer-events:none}
.tg-search-input{width:100%;box-sizing:border-box;appearance:none;padding:8px 30px 8px 32px;
  border:1px solid #e6e6e6;border-radius:8px;background:#fff;outline:none;
  font-family:'Inter','PingFang SC','Microsoft YaHei',sans-serif;font-size:13px;font-weight:500;color:#111;
  transition:border-color .15s,box-shadow .15s}
.tg-search-input::placeholder{color:#bbb}
.tg-search-input:hover{border-color:#ccc}
.tg-search-input:focus{border-color:#1a1a1a;box-shadow:0 0 0 3px rgba(26,26,26,.06)}
.tg-search-clear{position:absolute;right:8px;top:50%;transform:translateY(-50%);width:16px;height:16px;
  border:none;background:#e9e9e9;color:#666;border-radius:50%;cursor:pointer;font-size:12px;line-height:1;
  display:none;align-items:center;justify-content:center;padding:0}
.tg-search-input:not(:placeholder-shown) ~ .tg-search-clear{display:flex}
.tg-search-clear:hover{background:#d6d6d6;color:#111}
.tg-search:focus-within .tg-search-clear{display:flex}
/* 候选框顶部 4 件套筛选（全部类型 / 全部市 / 全部区 / 默认排序）。
   客户端联动 .tg-row 的 data-* 属性，change 即时隐藏/重排，无需往返 Python。 */
.tg-filters{display:flex;gap:8px;padding:14px 0 16px;border-bottom:1px solid #ececec;margin-bottom:12px;flex-shrink:0}
.tg-filters select{appearance:none;-webkit-appearance:none;flex:1;min-width:0;padding:9px 26px 9px 12px;
  border:1px solid #e3e3e3;border-radius:8px;background:#fff;
  font-family:'Inter',sans-serif;font-size:13px;font-weight:500;color:#111;cursor:pointer;
  background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='10' height='10' viewBox='0 0 10 10'><path d='M2 4l3 3 3-3' stroke='%23888' stroke-width='1.4' fill='none' stroke-linecap='round'/></svg>");
  background-repeat:no-repeat;background-position:right 10px center;background-size:10px 10px;
  position:relative;overflow:hidden}
.tg-filters select:hover{border-color:#bbb}
.tg-filters select:focus{outline:none;border-color:#1a1a1a}
/* 二级联动多选下拉（市 / 区）：按钮 + 浮层菜单，区选项随已选市级联 */
.tg-dd{position:relative;flex:1;min-width:0}
.tg-dd-btn{width:100%;padding:9px 26px 9px 12px;border:1px solid #e3e3e3;border-radius:8px;
  background:#fff;font-family:'Inter',sans-serif;font-size:13px;font-weight:500;color:#111;
  cursor:pointer;text-align:left;position:relative;overflow:hidden;
  background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='10' height='10' viewBox='0 0 10 10'><path d='M2 4l3 3 3-3' stroke='%23888' stroke-width='1.4' fill='none' stroke-linecap='round'/></svg>");
  background-repeat:no-repeat;background-position:right 10px center;background-size:10px 10px}
.tg-dd-btn:hover{border-color:#bbb}
.tg-dd.open .tg-dd-btn{border-color:#1a1a1a}
.tg-dd-badge{color:#1a1a1a;font-weight:700;margin-left:2px}
.tg-dd-menu{display:none;position:absolute;top:calc(100% + 6px);left:0;right:0;z-index:30;
  background:#fff;border:1px solid #e3e3e3;border-radius:10px;box-shadow:0 8px 24px rgba(0,0,0,.12);
  padding:8px;max-height:260px;overflow:auto}
.tg-dd.open .tg-dd-menu{display:block}
.tg-dd-all{display:block;padding:6px 8px;font-size:12px;color:#888;border-bottom:1px solid #f0f0f0;margin-bottom:4px;cursor:pointer;position:relative;overflow:hidden}
.tg-dd-opts label{display:block;padding:6px 8px;font-size:13px;color:#222;cursor:pointer;border-radius:6px;position:relative;overflow:hidden}
.tg-dd-opts label:hover{background:#f6f6f6}
.tg-dd-opts input{margin-right:8px;vertical-align:middle}
/* 可搜索下拉（排序）：菜单顶部搜索框，边框/阴影与普通菜单一致 */
.tg-dd-searchbox{padding:4px 4px 8px;border-bottom:1px solid #f0f0f0;margin-bottom:6px}
.tg-dd-search-input{width:100%;box-sizing:border-box;appearance:none;padding:6px 10px;
  border:1px solid #e3e3e3;border-radius:6px;background:#fff;outline:none;
  font-family:'Inter','PingFang SC','Microsoft YaHei',sans-serif;font-size:12px;font-weight:500;color:#111;
  transition:border-color .15s,box-shadow .15s}
.tg-dd-search-input::placeholder{color:#bbb}
.tg-dd-search-input:focus{border-color:#1a1a1a;box-shadow:0 0 0 3px rgba(26,26,26,.06)}
.tg-dd-search .tg-dd-opts label.empty{display:none}
.tg-row{display:grid;grid-template-columns:1fr 60px 26px;align-items:center;gap:12px;
  padding:14px 12px;border-bottom:1px solid #f0f0f0;border-radius:8px;
  transition:box-shadow .18s,background .18s;position:relative;overflow:hidden}
.tg-row .name{font-family:'Cormorant Garamond','PingFang SC',serif;font-style:italic;font-weight:500;
  font-size:19px;line-height:1.15;color:#0a0a0a;margin:0 0 3px}
.tg-row .sub{font-size:11px;color:#888;line-height:1.5;letter-spacing:.1px}
.tg-row .sub .dot{margin:0 5px;color:#c9c9c9}
.tg-row .sub .brand, .tg-row .sub .open{color:#7aa6e6;font-weight:500}
.tg-row .sub .score{font-family:'Cormorant Garamond','PingFang SC',serif;font-style:italic;font-weight:600;color:#444}
.tg-row .price{font-family:'Inter',sans-serif;font-weight:700;font-size:19px;color:#0a0a0a;
  text-align:right;line-height:1;letter-spacing:-.3px}
.tg-row .price .qi{font-size:10px;font-weight:500;color:#aaa;margin-left:2px;letter-spacing:0}
.tg-row .price.sold{color:#aaa;font-weight:600;font-size:13px;letter-spacing:1px}
/* radio：可点击效果——白底黑描边圆形，缩小 + 加粗线条，hover 填充 + 轻微缩放 */
.tg-row .radio{width:20px;height:20px;border:2px solid #1a1a1a;border-radius:50%;
  display:flex;align-items:center;justify-content:center;margin-left:auto;background:#fff;
  cursor:pointer;transition:background .15s,transform .15s,box-shadow .15s;
  box-shadow:0 0 0 0 rgba(26,26,26,0)}
.tg-row:hover .radio{background:#f5f5f5;transform:scale(1.1)}
.tg-row .radio:hover{background:#1a1a1a;box-shadow:0 0 0 4px rgba(26,26,26,.10)}
.tg-row .radio.on{background:#1a1a1a}
.tg-row .radio.on::after{content:"";width:7px;height:7px;border-radius:50%;background:#fff}
/* 整行可点击——点击 radio 同时整行也响应；.on 为选中态。
   点击时扩大阴影面积，内边距保留，使阴影与文字之间留出留白 */
.tg-row{cursor:pointer}
.tg-row:hover{background:#fafafa;box-shadow:0 0 0 1px #f0f0f0 inset}
.tg-row.on{background:#f4f4f4;box-shadow:0 6px 20px rgba(0,0,0,.10),0 0 0 1px #e8e8e8 inset}
.tg-row.on .radio{background:#1a1a1a}
.tg-row.on .radio::after{content:"";width:7px;height:7px;border-radius:50%;background:#fff}
.tg-foot{margin-top:18px;font-size:11px;color:#aaa;letter-spacing:.5px;text-align:right;text-transform:uppercase}
.tg-no-data{padding:36px 0;text-align:center;color:#888;font-size:14px}
/* 波纹动画 */
@keyframes ripple-animation{
  to{ transform:scale(4); opacity:0; }
}
.tg-row .ripple, .tg-dd-btn .ripple, .tg-search .ripple, .tg-filters select .ripple,
.tg-dd-all .ripple, .tg-dd-opts label .ripple{
  position:absolute;border-radius:50%;transform:scale(0);
  animation:ripple-animation .6s linear;
  background:rgba(30,111,255,.15);pointer-events:none;
}
</style>
"""


def _safe(s: object) -> str:
    if s is None:
        return ""
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


# 查询中占位
_THIRDGINGER_LOADING_HTML = (
    _THIRDGINGER_CSS
    + """
<div class="tg-list">
  <div class="tg-meta-top">SEARCHING…</div>
  <h2 class="tg-title">FINDING<br>HOTELS</h2>
  <div class="tg-list-body" style="padding:48px 36px;display:flex;flex-direction:column;align-items:center;gap:18px">
    <div style="display:flex;gap:8px">
      <span class="tg-dot" style="width:10px;height:10px;border-radius:50%;background:#222;animation:tg-bounce 1.2s ease-in-out infinite"></span>
      <span class="tg-dot" style="width:10px;height:10px;border-radius:50%;background:#222;animation:tg-bounce 1.2s ease-in-out .15s infinite"></span>
      <span class="tg-dot" style="width:10px;height:10px;border-radius:50%;background:#222;animation:tg-bounce 1.2s ease-in-out .3s infinite"></span>
    </div>
    <div style="font-family:'Inter',sans-serif;font-size:12px;letter-spacing:4px;color:#999;margin-top:8px">
      请稍候，正在为您查询实时价格
    </div>
  </div>
  <div class="tg-foot">— 数据加载中 —</div>
</div>
<style>
@keyframes tg-bounce{
  0%,80%,100%{transform:scale(.4);opacity:.35}
  40%{transform:scale(1);opacity:1}
}
</style>
"""
)


def _build_thirdginger_list_html(data: "pd.DataFrame", rows_only: bool = False) -> str:
    if data.empty:
        if rows_only:
            return ""
        return '<div class="tg-list"><div class="tg-foot">— 暂无酒店 —</div></div>'
    n = len(data)
    rows: list[str] = []

    types_set: set[str] = set()
    cities_set: set[str] = set()
    dists_map: dict[str, set[str]] = {}
    for idx, (_, r) in enumerate(data.iterrows()):
        name = _safe(r.get("酒店名称")) or "（未命名）"
        brand = _safe(r.get("酒店类型"))
        open_date_raw = r.get("开业时间") or "—"
        open_date = _safe(open_date_raw) if open_date_raw not in ("—", "") else "—"
        loc = _safe(r.get("位置"))
        biz = _safe(r.get("地段/商圈"))
        room = _safe(r.get("房型")) or "—"
        full = r.get("是否有房") == "满房"
        member_price = r.get("铂金会员价")
        score_raw = r.get("评分")
        try:
            score_v = None if score_raw is None or pd.isna(score_raw) else float(score_raw)
        except Exception:
            score_v = None
        score_html = f'<span class="score">{score_v:.1f}分</span>' if score_v is not None else ""

        # 第一行：类型 · 开业时间 · 评分（评分放到最后，与酒店名同字体）
        top_parts: list[str] = []
        if brand:
            top_parts.append(f'<span class="brand">{brand}</span>')
        if open_date not in ("—", ""):
            top_parts.append(f'<span class="open">{open_date}</span>')
        if score_html:
            top_parts.append(score_html)
        sub_top = '<span class="dot">·</span>'.join(top_parts) if top_parts else "—"
        # 第二行：位置（市区 · 商圈/位置）
        sub2_parts: list[str] = []
        if loc:
            sub2_parts.append(loc)
        if biz and biz not in ("—", "") and (not loc or biz != loc):
            sub2_parts.append(biz)
        sub_mid = '<span class="dot">·</span>'.join(sub2_parts) if sub2_parts else ""
        # 第三行：房型（仅展示低价房型）
        sub_bottom = f"房型 {room}" if room and room != "—" else ""

        if member_price is not None and not full:
            price_html = f"¥{member_price:,.0f}<span class=\"qi\">起</span>"
            price_cls = "price"
        else:
            price_html = "满房"
            price_cls = "price sold"


        lat_s = "" if r.get("latitude") is None else f"{float(r['latitude']):.6f}"
        lng_s = "" if r.get("longitude") is None else f"{float(r['longitude']):.6f}"
        key_s = f"h{r.get('chainId') or idx}"
        type_v = (r.get("酒店类型") or "").strip()
        pos_v = r.get("位置")
        city_v = _city_of(pos_v)
        dist_v = _district_of(pos_v)
        price_raw = r.get("铂金会员价")
        try:
            price_attr = "" if price_raw is None or pd.isna(price_raw) else f"{float(price_raw)}"
        except Exception:
            price_attr = ""
        open_attr = _open_date_short(r.get("开业时间"))
        types_set.add(type_v or "其他")
        if city_v:
            cities_set.add(city_v)
            dists_map.setdefault(city_v, set()).add(dist_v)
        score_raw = r.get("评分")
        try:
            score_attr = "" if score_raw is None or pd.isna(score_raw) else f"{float(score_raw)}"
        except Exception:
            score_attr = ""
        rows.append(f"""
        <div class="tg-row" data-key="{_safe(key_s)}" data-lat="{lat_s}" data-lng="{lng_s}"
             data-type="{_safe(type_v)}" data-city="{_safe(city_v)}" data-district="{_safe(dist_v)}"
             data-price="{price_attr}" data-open="{_safe(open_attr)}" data-score="{score_attr}"
             onclick="window.__atourFocusHotel && window.__atourFocusHotel(this.dataset.key, this.dataset.lat, this.dataset.lng, event)">
          <div>
            <div class="name">{name}</div>
            <div class="sub">{sub_top}</div>
            <div class="sub">{sub_mid}</div>
            <div class="sub">{sub_bottom}</div>
          </div>
          <div class="{price_cls}">{price_html}</div>
          <div class="radio" data-key="{_safe(key_s)}"></div>
        </div>
        """)

    # 焦点脚本
    focus_script = """
<script>
window.__ATOUR_LIST = true;

// 父页面推送的增量更新（不重建 iframe → 保留滚动位置 + 选中态外的所有内容）
window.__atourUpdateRows = function(htmlFragment, n) {
  try {
    const body = document.querySelector('.tg-list-body');
    if (!body) return;
    // 增量刷新前记录当前选中行 key（__focusedKey 或 DOM 上的 .on），
    // 替换行区 DOM 后若该行仍在，则重新加回 .on 高亮，避免同步期间选中态被打断。
    const selRow = body.querySelector('.tg-row.on');
    const keepKey = (selRow && selRow.dataset.key) || window.__focusedKey || null;
    const st = body.scrollTop;
    body.innerHTML = htmlFragment;
    body.scrollTop = st;
    if (keepKey) {
      const row = body.querySelector('.tg-row[data-key="' + keepKey + '"]');
      if (row) {
        row.classList.add('on');
        const radio = row.querySelector('.radio');
        if (radio) radio.classList.add('on');
      }
    }
    const meta = document.querySelector('.tg-meta-top');
    if (meta) meta.textContent = n + ' HOTELS FOUND';
    const foot = document.querySelector('.tg-foot');
    if (foot) foot.textContent = '— 共 ' + n + ' 家酒店 ·';
    // 增量刷新后按当前筛选（类型/市/区/排序）重新过滤新行，保持选中态与计数一致
    if (typeof window.__atourFilter === 'function') window.__atourFilter();
  } catch(e) { console.error('updateRows', e); }
};

// 向地图 iframe（parent 页面中带 __ATOUR_MAP_TOKEN 的那个）发送消息
function atourNotifyMap(msg) {
  try {
    const frames = window.parent.document.querySelectorAll('iframe');
    for (let i = 0; i < frames.length; i++) {
      const w = frames[i].contentWindow;
      if (w && w.__ATOUR_MAP_TOKEN) w.postMessage(msg, '*');
    }
  } catch(e) { console.error('atourNotifyMap', e); }
}

// 清除所有行高亮
function atourClearHighlight() {
  document.querySelectorAll('.tg-row').forEach(function(r){
    r.classList.remove('on');
    const radio = r.querySelector('.radio');
    if (radio) radio.classList.remove('on');
  });
  window.__focusedKey = null;
}

// 高亮指定行（记录 __focusedKey，供 updateRows 增量刷新后恢复选中态）
function atourHighlight(key) {
  document.querySelectorAll('.tg-row').forEach(function(r){
    const on = r.dataset.key === key;
    r.classList.toggle('on', on);
    const radio = r.querySelector('.radio');
    if (radio) radio.classList.toggle('on', on);
  });
  window.__focusedKey = key;
  // 自动滚动到该行（行区在视口外时 scrollIntoView 到可见位置）
  const row = document.querySelector('.tg-row[data-key="' + key + '"]');
  if (row && typeof row.scrollIntoView === 'function') {
    row.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }
}

// 波纹效果（支持 MouseEvent 和没有事件对象的情况）
function createRipple(e, el) {
  const ripple = document.createElement('span');
  ripple.className = 'ripple';
  const rect = el.getBoundingClientRect();
  const size = Math.max(rect.width, rect.height);
  let cx, cy;
  if (e && typeof e.clientX === 'number') {
    cx = e.clientX; cy = e.clientY;
  } else {
    cx = rect.left + rect.width/2; cy = rect.top + rect.height/2;
  }
  ripple.style.width = ripple.style.height = size + 'px';
  ripple.style.left = (cx - rect.left - size/2) + 'px';
  ripple.style.top = (cy - rect.top - size/2) + 'px';
  el.appendChild(ripple);
  setTimeout(() => ripple.remove(), 600);
}

// 列表行点击：已选中 → 取消高亮 + 地图恢复全部气泡（保持缩放）；未选中 → 高亮 + 地图聚焦 10km
window.__atourFocusHotel = function(key, lat, lng, e) {
  const row = document.querySelector('.tg-row[data-key="' + key + '"]');
  if (row && e) createRipple(e, row);
  const wasOn = !!(row && row.classList.contains('on'));
  if (wasOn) {
    atourClearHighlight();
    atourNotifyMap({type:'atour:clearFocus'});
  } else {
    atourHighlight(key);
    atourNotifyMap({type:'atour:focusHotel', key:key, lat:Number(lat), lng:Number(lng)});
  }
};
// 地图气泡点击 → 列表行高亮；再次点击同一气泡 → 取消高亮 + 地图恢复全部气泡
// 父页面推送 atour:updateRows → 仅更新行区 DOM（保留滚动位置）
window.addEventListener('message', function(e){
  if (!e || !e.data) return;
  if (e.data.type === 'atour:focusBubble' && e.data.key) {
    const row = document.querySelector('.tg-row[data-key="' + e.data.key + '"]');
    const finish = function(){
      // 行滚动到位后再叠加波纹，保证波纹起点落在行内可见区域
      if (row) {
        const rect = row.getBoundingClientRect();
        const fakeEvent = { clientX: rect.left + rect.width/2, clientY: rect.top + rect.height/2 };
        createRipple(fakeEvent, row);
      }
    };
    const wasOn = !!(row && row.classList.contains('on'));
    if (wasOn) {
      atourClearHighlight();
      atourNotifyMap({type:'atour:clearFocus'});
      finish();
    } else {
      atourHighlight(e.data.key);
      // 先滚动到该行，滚动完成后再触发波纹（行可能在视口外）
      if (row && row.scrollIntoView) {
        let done = false;
        const cb = function(){ if (done) return; done = true; finish(); };
        row.scrollIntoView({ block: 'center', behavior: 'smooth' });
        // 平滑滚动可能不触发 scrollend（兼容性兜底：超时后也强制触发）
        setTimeout(cb, 420);
      } else {
        finish();
      }
    }
  } else if (e.data.type === 'atour:updateRows' && typeof window.__atourUpdateRows === 'function') {
    window.__atourUpdateRows(e.data.html || '', e.data.n || 0);
  }
});

// ===== 客户端筛选 + 排序（不往返 Python）=====
// 类型 / 排序：单选 select；市 / 区：二级联动 + 多选下拉（市选中后区选项级联；两者均可多选）
function tgEsc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){
  return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
function tgSelTypes(){
  const b=document.querySelector('.tg-dd[data-k="type"]'); if(!b) return [];
  return Array.from(b.querySelectorAll('.tg-dd-opts input[type=checkbox]:checked')).map(c=>c.value);
}
function tgSelCities(){
  const b=document.querySelector('.tg-dd[data-k="city"]'); if(!b) return [];
  return Array.from(b.querySelectorAll('.tg-dd-opts input[type=checkbox]:checked')).map(c=>c.value);
}
function tgSelDists(){
  const b=document.querySelector('.tg-dd[data-k="dist"]'); if(!b) return [];
  return Array.from(b.querySelectorAll('.tg-dd-opts input[type=checkbox]:checked')).map(c=>c.value);
}
function tgBadge(box){
  const badge=box.querySelector('.tg-dd-badge'); if(!badge) return;
  const k=box.getAttribute('data-k');
  let n=0;
  if(k==='type') n=tgSelTypes().length;
  else if(k==='city') n=tgSelCities().length;
  else if(k==='dist') n=tgSelDists().length;
  badge.textContent = n? (' '+n) : '';
}
// 区选项随已选市级联：未选市→全部区；选市→这些市的区并集；保留已勾选项
function tgBuildDist(){
  const box=document.querySelector('.tg-dd[data-k="dist"]'); if(!box) return;
  const opts=box.querySelector('.tg-dd-opts');
  const map=JSON.parse(opts.getAttribute('data-dists')||'{}');
  const cities=tgSelCities();
  const dset=new Set();
  if(cities.length===0){ Object.values(map).forEach(a=>a.forEach(d=>dset.add(d))); }
  else { cities.forEach(c=>(map[c]||[]).forEach(d=>dset.add(d))); }
  const dists=Array.from(dset).sort();
  const prev=new Set(tgSelDists());
  opts.innerHTML=dists.map(d=>'<label><input type="checkbox" value="'+tgEsc(d)+'" '+(prev.has(d)?'checked':'')+'>'+tgEsc(d)+'</label>').join('');
  opts.querySelectorAll('input').forEach(inp=>inp.addEventListener('change', function(e){ tgOnSpec(e, box); }));
  tgBadge(box);
}
function tgOnAll(e, box){
  const v=e.target.checked;
  box.querySelectorAll('.tg-dd-opts input[type=checkbox]').forEach(inp=>{ inp.checked=v; });
  if(box.getAttribute('data-k')==='city') tgBuildDist();
  tgBadge(box);
  window.__atourFilter();
}
function tgOnSpec(e, box){
  const specs=box.querySelectorAll('.tg-dd-opts input[type=checkbox]');
  const all=box.querySelector('.tg-dd-all input');
  if(all) all.checked = specs.length>0 && Array.from(specs).every(s=>s.checked);
  if(box.getAttribute('data-k')==='city') tgBuildDist();
  tgBadge(box);
  window.__atourFilter();
}
function tgBindDD(box){
  const all=box.querySelector('.tg-dd-all input');
  if(all) all.addEventListener('change', function(e){ tgOnAll(e, box); });
  box.querySelectorAll('.tg-dd-opts input').forEach(inp=>inp.addEventListener('change', function(e){ tgOnSpec(e, box); }));
}
// 主筛选：类型(多选) + 市(多选) + 区(多选) + 排序
window.__atourFilter = function() {
  try {
    const s=window.__tgSortValue || '';
    const body=document.querySelector('.tg-list-body');
    if(!body) return;
    const types=tgSelTypes();
    const cities=tgSelCities();
    const dists=tgSelDists();
    // 搜索关键字（与筛选 AND 生效）：匹配整行文本（名称/类型/位置/地段/房型/城市/区）
    const qEl=document.querySelector('.tg-search-input');
    const q=(qEl?qEl.value.trim():'').toLowerCase();
    const rows=Array.from(body.querySelectorAll('.tg-row'));
    let shown=0;
    rows.forEach(r=>{
      const okType=types.length===0||types.indexOf(r.dataset.type)>=0;
      const okCity=cities.length===0||cities.indexOf(r.dataset.city)>=0;
      const okDist=dists.length===0||dists.indexOf(r.dataset.district)>=0;
      const okSearch=!q||(r.textContent||'').toLowerCase().indexOf(q)>=0;
      const ok=okType&&okCity&&okDist&&okSearch;
      r.style.display=ok?'':'none';
      if(ok) shown++;
    });
    if(s){
      const vis=rows.filter(r=>r.style.display!=='none');
      vis.sort((a,b)=>{
        if(s==='price-asc'||s==='price-desc'){
          const pa=parseFloat(a.dataset.price),pb=parseFloat(b.dataset.price);
          const an=Number.isNaN(pa),bn=Number.isNaN(pb);
          if(an&&bn)return 0; if(an)return 1; if(bn)return -1;
          return s==='price-asc'?pa-pb:pb-pa;
        }
        if(s==='open-desc') return (b.dataset.open||'').localeCompare(a.dataset.open||'');
        if(s==='score-desc'){
          const sa=parseFloat(a.dataset.score),sb=parseFloat(b.dataset.score);
          const an=Number.isNaN(sa),bn=Number.isNaN(sb);
          if(an&&bn) return (b.dataset.open||'').localeCompare(a.dataset.open||'');
          if(an) return 1; if(bn) return -1;
          if(sb!==sa) return sb-sa;
          return (b.dataset.open||'').localeCompare(a.dataset.open||'');
        }
        return 0;
      });
      const frag=document.createDocumentFragment();
      vis.forEach(r=>frag.appendChild(r));
      body.appendChild(frag);
    }
    // 列表筛选/排序后，把可见行 key 同步给地图 iframe，让气泡与列表联动（类型/市/区/排序变化均生效）
    try {
      const visibleKeys = [];
      rows.forEach(function(r){ if(r.style.display !== 'none') visibleKeys.push(r.dataset.key); });
      atourNotifyMap({type:'atour:filterBubbles', keys: visibleKeys});
    } catch(e) {}
    const meta=document.querySelector('.tg-meta-top');
    if(meta) meta.textContent=shown+' HOTELS FOUND';
    const foot=document.querySelector('.tg-foot');
    if(foot) foot.textContent='— 共 '+shown+' 家酒店 ·';
  } catch(e){ console.error('atourFilter', e); }
};
// 下拉开合
document.querySelectorAll('.tg-dd .tg-dd-btn').forEach(btn=>{
  btn.addEventListener('click', function(e){
    e.stopPropagation();
    createRipple(e, btn);
    const dd=btn.closest('.tg-dd');
    const open=dd.classList.contains('open');
    document.querySelectorAll('.tg-dd.open').forEach(x=>x.classList.remove('open'));
    if(!open) dd.classList.add('open');
  });
});
document.addEventListener('click', function(e){
  if(!e.target.closest || !e.target.closest('.tg-dd')){
    document.querySelectorAll('.tg-dd.open').forEach(x=>x.classList.remove('open'));
  }
});
document.querySelectorAll('.tg-filters select').forEach(el=>el.addEventListener('change', window.__atourFilter));
document.querySelectorAll('.tg-dd').forEach(tgBindDD);
// 类型下拉按钮文字初始化
const typeBox=document.querySelector('.tg-dd[data-k="type"]'); if(typeBox) tgBadge(typeBox);
// 搜索框：点击波纹 + 输入即时过滤（与筛选/排序同时生效）；清除按钮清空并恢复
const tgSearchWrap=document.querySelector('.tg-search');
if(tgSearchWrap){
  tgSearchWrap.addEventListener('click', function(e){
    if(e.target.closest('.tg-search-clear')) return;
    createRipple(e, tgSearchWrap);
  });
}
const tgSearchInput=document.querySelector('.tg-search-input');
if(tgSearchInput){
  tgSearchInput.addEventListener('input', window.__atourFilter);
  tgSearchInput.addEventListener('keydown', function(e){
    if(e.key==='Escape'){ tgSearchInput.value=''; window.__atourFilter(); tgSearchInput.blur(); }
  });
}
const tgSearchClear=document.querySelector('.tg-search-clear');
if(tgSearchClear){
  tgSearchClear.addEventListener('click', function(e){
    createRipple(e, tgSearchClear);
    tgSearchInput.value='';
    window.__atourFilter();
    tgSearchInput.focus();
  });
}
// 排序下拉（可搜索单选）：点击选项 → 选中并关闭；搜索框输入 → 实时过滤选项
window.__tgSortValue = '';
const sortBox = document.querySelector('.tg-dd[data-k="sort"]');
if (sortBox) {
  const sortBtn = sortBox.querySelector('.tg-dd-btn');
  const sortInput = sortBox.querySelector('.tg-dd-search-input');
  const sortOpts = sortBox.querySelectorAll('.tg-dd-opts label');
  sortInput && sortInput.addEventListener('input', function(){
    const q = this.value.trim().toLowerCase();
    sortOpts.forEach(function(lb){
      const txt = (lb.textContent || '').toLowerCase();
      lb.classList.toggle('empty', q && txt.indexOf(q) < 0);
    });
  });
  sortInput && sortInput.addEventListener('click', function(e){ e.stopPropagation(); });
  sortOpts.forEach(function(lb){
    lb.addEventListener('click', function(e){
      e.stopPropagation();
      createRipple(e, lb);
      window.__tgSortValue = lb.getAttribute('data-value') || '';
      const txt = (lb.textContent || '').trim();
      sortBtn.textContent = txt || '默认排序';
      sortBox.classList.remove('open');
    });
  });
}
// 下拉候选框（全部/选项）点击波纹 — 绑定在 tg-dd-menu 上利用事件委托，
// 可覆盖动态重建的区选项以及 checkbox 本身
document.querySelectorAll('.tg-dd').forEach(dd=>{
  const menu = dd.querySelector('.tg-dd-menu');
  if (!menu) return;
  menu.addEventListener('mousedown', function(e){
    const item = e.target.closest('.tg-dd-all, .tg-dd-opts label');
    if (item) createRipple(e, item);
  });
});
tgBuildDist();
</script>
"""

    if rows_only:
        return "".join(rows)

    # 客户端筛选
    types_sorted = sorted({t for t in types_set if t})
    cities_sorted = sorted({c for c in cities_set if c})
    dists_union = sorted({d for ds in dists_map.values() for d in ds if d})
    type_opts_html = "".join(
        f'<label><input type="checkbox" value="{_safe(t)}"> {_safe(t)}</label>' for t in types_sorted
    )
    city_opts_html = "".join(
        f'<label><input type="checkbox" value="{_safe(c)}"> {_safe(c)}</label>' for c in cities_sorted
    )
    # 市→区 映射（供区选项级联）：键/值均过滤 HTML 特殊字符；JSON 用单引号属性包裹避免与内部双引号冲突
    dists_json = json.dumps(
        {_safe(k): sorted(_safe(d) for d in v) for k, v in dists_map.items()},
        ensure_ascii=False,
    )
    dist_opts_html = "".join(
        f'<label><input type="checkbox" value="{_safe(d)}"> {_safe(d)}</label>' for d in dists_union
    )
    filters_html = (
        '<div class="tg-filters">'
        + '<div class="tg-dd" data-k="type">'
        +   '<button type="button" class="tg-dd-btn">类型</button>'
        +   '<div class="tg-dd-menu">'
        +     '<label class="tg-dd-all"><input type="checkbox"> 全部类型</label>'
        +     f'<div class="tg-dd-opts">{type_opts_html}</div>'
        +   '</div>'
        + '</div>'
        + '<div class="tg-dd" data-k="city">'
        +   '<button type="button" class="tg-dd-btn">市</button>'
        +   '<div class="tg-dd-menu">'
        +     '<label class="tg-dd-all"><input type="checkbox"> 全部市</label>'
        +     f'<div class="tg-dd-opts">{city_opts_html}</div>'
        +   '</div>'
        + '</div>'
        + '<div class="tg-dd" data-k="dist">'
        +   '<button type="button" class="tg-dd-btn">区</button>'
        +   '<div class="tg-dd-menu">'
        +     '<label class="tg-dd-all"><input type="checkbox"> 全部区</label>'
        +     f'<div class="tg-dd-opts" data-dists=\'{dists_json}\'>{dist_opts_html}</div>'
        +   '</div>'
        + '</div>'
        + '<div class="tg-dd tg-dd-search" data-k="sort">'
        +   '<button type="button" class="tg-dd-btn">默认排序</button>'
        +   '<div class="tg-dd-menu">'
        +     '<div class="tg-dd-searchbox">'
        +       '<input type="text" class="tg-dd-search-input" placeholder="搜索排序…" autocomplete="off" spellcheck="false" />'
        +     '</div>'
        +     '<div class="tg-dd-opts">'
        +       '<label data-value=""><input type="radio" name="tg-sort" value=""> 默认排序</label>'
        +       '<label data-value="price-asc"><input type="radio" name="tg-sort" value="price-asc"> 价格升序</label>'
        +       '<label data-value="price-desc"><input type="radio" name="tg-sort" value="price-desc"> 价格降序</label>'
        +       '<label data-value="open-desc"><input type="radio" name="tg-sort" value="open-desc"> 开业时间降序</label>'
        +       '<label data-value="score-desc"><input type="radio" name="tg-sort" value="score-desc"> 评分降序</label>'
        +     '</div>'
        +   '</div>'
        + '</div>'
        + '</div>'
    )
    # 搜索框
    search_html = (
        '<div class="tg-search">'
        + '<svg class="tg-search-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        + 'stroke-width="1.6" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></svg>'
        + '<input type="text" class="tg-search-input" data-search placeholder="搜索酒店名称 / 位置 / 商圈…" '
        + 'autocomplete="off" spellcheck="false" />'
        + '<button type="button" class="tg-search-clear" data-search-clear aria-label="清除">×</button>'
        + '</div>'
    )
    body = (
        '<div class="tg-list">'
        + f'<div class="tg-meta-top">{n} HOTELS FOUND</div>'
        + f'<h2 class="tg-title">AVAILABLE<br>STAYS</h2>'
        + search_html
        + filters_html
        + '<div class="tg-list-body">' + "".join(rows) + '</div>'
        + f'<div class="tg-foot">— 共 {n} 家酒店 ·</div>'
        + '</div>'
    )

    # 完整 iframe 文档
    return (
        "<!DOCTYPE html><html><head><meta charset=\"utf-8\">"
        + _THIRDGINGER_CSS
        + "<style>html,body{margin:0;padding:0;height:100%}</style>"
        + "</head><body>"
        + body
        + focus_script
        + "</body></html>"
    )


def _render_thirdginger_list(data: "pd.DataFrame") -> None:
    if data.empty:
        st.markdown("所选条件下没有酒店。", unsafe_allow_html=False)
        return
    components.html(_build_thirdginger_list_html(data), height=720)


def render_results(records: list[dict]) -> None:
    data = pd.DataFrame(records)
    if data.empty:
        st.info("未查询到酒店或房型。")
        return

    # 左：类型筛选；右：排序
    col_filter, col_sort = st.columns(2)
    with col_filter:
        chosen_types = st.multiselect("酒店类型筛选", HOTEL_TYPE_OPTIONS)
    with col_sort:

        sort_choice = st.selectbox("排序", _SORT_OPTIONS, index=_SORT_OPTIONS.index("开业时间 降序"))

    if chosen_types:
        data = data[data["酒店类型"].isin(chosen_types)]
        if data.empty:
            st.info(f"所选类型（{'、'.join(chosen_types)}）下没有酒店，请调整筛选。")
            return

    # 位置两级筛选
    data["_位置市"] = data["位置"].map(_city_of)
    data["_位置区"] = data["位置"].map(_district_of)
    col_city, col_dist = st.columns(2)
    with col_city:
        city_options = sorted({v for v in data["_位置市"] if v})
        city_choice = st.multiselect("位置 · 市", city_options, placeholder="全部")
    with col_dist:
        if not city_choice:
            dists = sorted({v for v in data["_位置区"] if v})
        else:
            dists = sorted({v for v in data.loc[data["_位置市"].isin(city_choice), "_位置区"] if v})
        dist_choice = st.multiselect("位置 · 区", dists, placeholder="全部")

    if city_choice:
        data = data[data["_位置市"].isin(city_choice)]
    if dist_choice:
        data = data[data["_位置区"].isin(dist_choice)]
    data = data.drop(columns=["_位置市", "_位置区"])
    if data.empty:
        st.info(f"所选位置（{city_choice} / {dist_choice}）下没有酒店，请调整筛选。")
        return

    field, _, direction = sort_choice.rpartition(" ")
    ascending = direction == "升序"
    if field == "开业时间":

        data["_sort"] = data["开业时间"].map(_open_date_sort_key)
    else:
        data["_sort"] = data[field]
    data = data.sort_values("_sort", ascending=ascending, na_position="last").drop(columns=["_sort"])

    # 双栏：地图左 + 列表右
    col_map, col_list = st.columns([3, 2], gap="small")
    with col_map:
        # 地图气泡联动
        _emit_map(data.to_dict("records"), fit=True)
    with col_list:
        _render_thirdginger_list(data)


# 顶部条样式
_TOP_BAR_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,400;0,500;0,600;1,400;1,500;1,600&family=Inter:wght@400;500;600;700&display=swap');
.tg-top{display:flex;justify-content:space-between;align-items:center;
  padding:14px 28px;background:#fff;font-family:'Inter','PingFang SC','Microsoft YaHei',sans-serif;
  border-top:1px solid #ececec;border-bottom:1px solid #ececec;margin:0 -1rem}
.tg-top .logo{font-family:'Cormorant Garamond','PingFang SC',serif;font-style:italic;font-weight:500;
  font-size:30px;line-height:1;color:#0a0a0a;letter-spacing:-.5px}
.tg-top .meta{display:flex;gap:48px;align-items:center}
.tg-top .meta .item{display:flex;flex-direction:column;gap:4px}
.tg-top .meta .lbl{font-size:10px;letter-spacing:1.6px;color:#888;font-weight:600;text-transform:uppercase;line-height:1}
.tg-top .meta .val{font-family:'Inter',sans-serif;font-size:14px;color:#111;font-weight:600;letter-spacing:.3px;line-height:1.2}
.tg-top .meta .val .sep{color:#bbb;margin:0 4px;font-weight:400}
.tg-top .avatar{width:36px;height:36px;border-radius:50%;border:1.5px solid #1a1a1a;flex-shrink:0;background:#fff;position:relative}
.tg-top .avatar::after{content:"";position:absolute;inset:6px;border-radius:50%;border:1px solid #1a1a1a}
</style>
"""


def _fmt_month_eng(d: date) -> str:
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    return f"{months[d.month - 1]} {d.day}"



def _render_filters(records_df: "pd.DataFrame") -> "pd.DataFrame":
    data = records_df.copy()
    if data.empty:
        return data
    c1, c2, c3, c4 = st.columns(4, gap="small")
    with c1:
        chosen_types = st.multiselect("酒店类型筛选", HOTEL_TYPE_OPTIONS, key="_f_types", label_visibility="visible", placeholder="全部")
    with c2:
        sort_choice = st.selectbox("排序", _SORT_OPTIONS,
                                   index=_SORT_OPTIONS.index("开业时间 降序"),
                                   key="_f_sort")
    with c3:
        data["_位置市"] = data["位置"].map(_city_of)
        city_options = sorted({v for v in data["_位置市"] if v})
        city_choice = st.multiselect("位置 · 市", city_options, key="_f_city", placeholder="全部")
    with c4:
        if not city_choice:
            dists = sorted({v for v in data["位置"].map(_district_of) if v})
        else:
            dists = sorted({v for v in data.loc[data["_位置市"].isin(city_choice), "位置"].map(_district_of) if v})
        dist_choice = st.multiselect("位置 · 区", dists, key="_f_dist", placeholder="全部")

    if chosen_types:
        data = data[data["酒店类型"].isin(chosen_types)]
    if city_choice:
        data = data[data["_位置市"].isin(city_choice)]
    if dist_choice:
        data = data[data["位置"].map(_district_of).isin(dist_choice)]
    data = data.drop(columns=["_位置市"], errors="ignore")

    field, _, direction = sort_choice.rpartition(" ")
    ascending = direction == "升序"
    if field == "开业时间":
        data["_sort"] = data["开业时间"].map(_open_date_sort_key)
    else:
        data["_sort"] = data[field]
    data = data.sort_values("_sort", ascending=ascending, na_position="last").drop(columns=["_sort"])
    return data


def _render_top_bar(location: str | None, dates) -> None:
    today = date.today()

    d_start, d_end = today + timedelta(days=1), today + timedelta(days=2)
    if isinstance(dates, tuple) and len(dates) == 2:
        a, b = dates[0], dates[1]
        if isinstance(a, date) and isinstance(b, date):
            d_start, d_end = a, b
    dates_str = f"{_fmt_month_eng(d_start)}<span class='sep'>—</span>{_fmt_month_eng(d_end)}"
    loc_str = location or "—"

    html = (
        _TOP_BAR_CSS
        + f"""
<div class="tg-top">
  <div class="logo">Atour Hotels</div>
  <div class="meta">
    <div class="item"><div class="lbl">Location</div><div class="val">{_safe(loc_str)}</div></div>
    <div class="item"><div class="lbl">Dates</div><div class="val">{dates_str}</div></div>
  </div>
  <div class="avatar"></div>
</div>
"""
    )
    st.html(html)


def _render_brand_inline() -> None:
    html = (
        _TOP_BAR_CSS
        + '<div class="tg-top" style="background:transparent;border:none;margin:0;'
          'padding:0;justify-content:flex-start;gap:18px">'
          '<div class="logo">Atour Hotels</div>'
          '<div class="avatar"></div>'
          '</div>'
    )
    st.html(html)




def _build_layout_js() -> str:
    return """
<script>
(function(){
  function fit(){
    try{
      var frames = parent.document.querySelectorAll('iframe');
      var vh = parent.window.innerHeight;
      // 每个大 iframe 从「自身顶部」撑到视口底（留 4px 余量），让地图/列表正好占满页面、不滚动。
      // 用各自 getBoundingClientRect().top 计算，避免被顶栏高度多算导致底部被裁切。
      frames.forEach(function(f){
        if (f.clientHeight > 200){
          var t = f.getBoundingClientRect().top;
          var target = Math.max(420, Math.round(vh - t - 4));
          f.style.height = target + 'px';
        }
      });
    }catch(e){}
  }
  if (parent.window){ parent.window.addEventListener('resize', fit); }
  fit();
  setInterval(fit, 200);
})();
</script>
"""


def _handle_url_query_params():
    try:
        qp = st.query_params
    except Exception:
        return

    auto = qp.get("auto")
    if auto != "1":
        return

    # 读取全部 location 参数（支持重复参数=多选）
    try:
        locations = qp.get_all("location")
    except Exception:
        locations = None
    if not locations:
        single = qp.get("location")
        locations = [single] if single else []


    processed_key = "_url_query_processed"
    current_sig = json.dumps({
        "scope": qp.get("scope"),
        "locations": locations,
        "check_in": qp.get("check_in"),
        "check_out": qp.get("check_out"),
    }, sort_keys=True, ensure_ascii=False)
    if st.session_state.get(processed_key) == current_sig:
        return

    scope = qp.get("scope", "city")

    cleaned: list[str] = []
    for loc in (locations or []):
        loc = (loc or "").strip()
        if loc and loc not in cleaned:
            cleaned.append(loc)
    if not cleaned:
        return

    check_in_str = qp.get("check_in", "")
    check_out_str = qp.get("check_out", "")

    try:
        check_in = date.fromisoformat(check_in_str)
        check_out = date.fromisoformat(check_out_str)
    except ValueError:
        return

    if check_out <= check_in:
        return


    try:
        qp.pop("auto", None)
    except Exception:
        pass

    st.session_state[processed_key] = current_sig
    st.session_state["loc_choice"] = "、".join(cleaned)
    st.session_state["dates"] = (check_in, check_out)
    st.session_state["_map_token"] = uuid.uuid4().hex
    st.session_state["_map_html"] = None
    st.session_state["_map_fit_count"] = -1
    st.session_state["_map_emitted"] = False
    st.session_state["_list_first_emit"] = True
    st.session_state["_is_searching"] = True
    st.session_state["_pending_search"] = {
        "locations": cleaned,
        "check_in": check_in,
        "check_out": check_out,
        "scope": scope if scope in ("city", "province") else "city",
        "enrich_open_date": True,  # UI 不再提供开关，默认开启
    }
    st.rerun()


def main() -> None:
    if "_pending_search" not in st.session_state:
        st.session_state.pop("_is_searching", None)


    _handle_url_query_params()

    # 首次进入页面时自动注入默认查询
    records = st.session_state.get("records")
    if "_pending_search" not in st.session_state and not records:
        st.session_state["loc_choice"] = "福州市"
        st.session_state["dates"] = (date.today() + timedelta(days=1), date.today() + timedelta(days=2))
        st.session_state["_map_token"] = uuid.uuid4().hex
        st.session_state["_map_html"] = None
        st.session_state["_map_fit_count"] = -1
        st.session_state["_map_emitted"] = False
        st.session_state["_list_first_emit"] = True
        st.session_state["_is_searching"] = True
        st.session_state["_pending_search"] = {
            "locations": ["福州市"],
            "check_in": date.today() + timedelta(days=1),
            "check_out": date.today() + timedelta(days=2),
            "scope": "city",
            "enrich_open_date": True,
        }
        st.rerun()

    # 主区（地图 + 列表）
    components.html(_build_layout_js(), height=1)
    pending = st.session_state.pop("_pending_search", None)
    if pending:
        # 查询中：双栏（左=地图壳，右=加载占位；数据到达时气泡+列表实时更新）
        col_map, col_list = st.columns([3, 2], gap="small")
        with col_map:
            _emit_map([], fit=False)
        with col_list:
            prog_status = st.empty()
            prog_status.caption(f"⏳ 开始查询「{'、'.join(pending.get('locations') or [pending.get('location', '')])}」…")
            list_holder = st.empty()
            list_holder.html(_THIRDGINGER_LOADING_HTML)

        def on_progress(partial_records, status):
            prog_status.caption(f"⏳ {status}")
            if partial_records:
                _emit_map(partial_records, fit=True)
                if st.session_state.get("_list_first_emit", True):
                    with list_holder.container():
                        components.html(
                            _build_thirdginger_list_html(pd.DataFrame(partial_records)),
                            height=720,
                        )
                    st.session_state["_list_first_emit"] = False
                else:
                    rows_html = _build_thirdginger_list_html(
                        pd.DataFrame(partial_records), rows_only=True
                    )
                    components.html(
                        f"<script>(function(){{const fs=parent.document.querySelectorAll('iframe');"
                        f"const rows={json.dumps(rows_html, ensure_ascii=False)};"
                        f"const n={len(partial_records)};"
                        f"for(let i=0;i<fs.length;i++){{const w=fs[i].contentWindow;"
                        f"if(w && w.__ATOUR_LIST){{w.postMessage({{type:'atour:updateRows',html:rows,n:n}},'*');break;}}}}}})();</script>",
                        height=1,
                    )

        # 多选查询
        locations = pending.get("locations") or [pending.get("location")]
        locations = [loc for loc in locations if loc]
        merged: list[dict[str, Any]] = []
        seen_keys: set[str] = set()
        failed_locs: list[str] = []

        for idx, loc in enumerate(locations, start=1):
            def _on_loc_progress(partial_records, status, _loc=loc, _idx=idx, _total=len(locations)):
                prefix = f"〔{_idx}/{_total} {_loc}〕" if _total > 1 else ""
                combined = merged + list(partial_records)
                on_progress(combined, f"{prefix}{status}")

            try:
                sub = fetch_atour_prices(
                    loc, pending["check_in"], pending["check_out"],
                    scope=pending["scope"], enrich_open_date=pending["enrich_open_date"],
                    token=ATOUR_TOKEN,
                    on_progress=_on_loc_progress,
                )
            except (ValueError, AtourAPIError, requests.RequestException, Exception) as exc:
                failed_locs.append(loc)
                on_progress(merged, f"〔{idx}/{len(locations)} {loc}〕查询失败：{exc}")
                continue
            for r in sub:
                key = f"{r.get('酒店名称')}|{r.get('位置')}"
                if key not in seen_keys:
                    seen_keys.add(key)
                    merged.append(r)
            on_progress(merged, f"〔{idx}/{len(locations)} {loc}〕完成（累计 {len(merged)} 家）")


        if not merged and failed_locs:
            recs = None
            exc_msg = "、".join(failed_locs)
            st.error(f"查询失败：{exc_msg} 均未返回数据（接口可能限流或临时不可用）。请稍后重试，或缩小选择范围。")
            components.html(_build_controller_js(st.session_state.get("_map_token"), [], False), height=1)
        else:
            recs = merged

        prog_status.empty()
        st.session_state["_is_searching"] = False
        if recs is None:
            list_holder.empty()
            return
        st.session_state["records"] = recs
        st.session_state["dates"] = (pending["check_in"], pending["check_out"])
        if not recs:
            st.warning(f"查询完成，但所选地点均未返回任何酒店。可调整城市/省份或日期后重试。")
        elif failed_locs:
            st.caption(f"⚠️ 部分地点查询失败：{'、'.join(failed_locs)}（可能被限流），已展示其余地点的结果。")
        records = recs
        # 地图更新
        _emit_map(recs, fit=True)
        # 列表更新
        with list_holder.container():
            components.html(_build_thirdginger_list_html(pd.DataFrame(recs)), height=720)
        return

    if records is not None:
        st.session_state["_map_emitted"] = False
        df_use = pd.DataFrame(records)
        col_map, col_list = st.columns([3, 2], gap="small")
        with col_map:
            _emit_map(df_use.to_dict("records"), fit=True)
        with col_list:
            _render_thirdginger_list(df_use)
    elif st.session_state.get("_is_searching"):
        col_map, col_list = st.columns([3, 2], gap="small")
        with col_map:
            _emit_map([], fit=False)
        with col_list:
            st.html(_THIRDGINGER_LOADING_HTML)
    else:
        st.info("等待查询：选择范围、地区与日期后开始。")
if __name__ == "__main__":
    main()
