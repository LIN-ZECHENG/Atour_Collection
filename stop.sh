#!/usr/bin/env bash
# 停止 Atour 统一项目的两个服务
pkill -f "astro preview" 2>/dev/null
pkill -f "streamlit.exe run app.py" 2>/dev/null
pkill -f "npm run preview" 2>/dev/null
echo "已尝试停止 Astro 预览与 Streamlit 服务。"
