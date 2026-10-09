@echo off
rem MemoIsle 扩展一键更新：下载最新扩展到本目录并打开扩展管理页。
rem 用法：双击本文件；或 install.cmd <API地址> 以指定后端。
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
exit /b %errorlevel%
