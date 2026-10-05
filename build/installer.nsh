!macro customInstall
  nsExec::ExecToLog 'powershell -NoProfile -Command "try { Add-MpPreference -ExclusionPath ''$InstDir'' -ErrorAction Stop } catch {}"'
!macroend

!macro customUnInstall
  nsExec::ExecToLog 'powershell -NoProfile -Command "try { Remove-MpPreference -ExclusionPath ''$InstDir'' -ErrorAction Stop } catch {}"'
!macroend
