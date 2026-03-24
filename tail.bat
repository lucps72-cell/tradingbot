@echo off
PowerShell Get-Content -Path "%1" -Wait -Tail 10 -Encoding UTF8