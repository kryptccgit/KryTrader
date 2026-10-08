; Krypt Trader NSIS installer add-ons.
; Loaded by electron-builder (see package.json -> build.nsis.include).

!macro customInstall
  ; Add an exclusion to the install dir so Windows Defender doesn't
  ; quarantine the bundled Python backend on first launch. This is a
  ; best-effort PowerShell call — silently no-op if it fails. The path is
  ; quoted so install dirs containing spaces (e.g. C:\Program Files\...) work.
  nsExec::ExecToLog 'powershell -NoProfile -Command "try { Add-MpPreference -ExclusionPath ''$InstDir'' -ErrorAction Stop } catch {}"'
!macroend

!macro customUnInstall
  ; Don't delete user data on uninstall — they keep their settings,
  ; profiles, credentials, and DB if they reinstall later. The user
  ; can clear via "Delete saved keys" in the API page first.
  ;
  ; But DO remove the Defender exclusion we added at install — otherwise it
  ; persists forever and whitelists this (now-empty) path from AV scanning.
  nsExec::ExecToLog 'powershell -NoProfile -Command "try { Remove-MpPreference -ExclusionPath ''$InstDir'' -ErrorAction Stop } catch {}"'
!macroend
