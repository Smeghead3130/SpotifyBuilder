@echo off
rem Runs spb from cmd.exe without Python needing to be on PATH.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0spb.ps1" %*
