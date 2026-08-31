; FileMind Phase 0 NSIS Installer Script
; Target: Windows 11 Clean Machine Distribution (Zero Dev Tooling Required)

!define PRODUCT_NAME "FileMind"
!define PRODUCT_VERSION "0.1.0"
!define PRODUCT_PUBLISHER "FileMind Team"
!define PRODUCT_DIR_REGKEY "Software\Microsoft\Windows\CurrentVersion\App Paths\FileMind.exe"
!define PRODUCT_UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${PRODUCT_NAME}"

SetCompressor /SOLID lzma

; Modern UI
!include "MUI2.nsh"

Name "${PRODUCT_NAME} ${PRODUCT_VERSION}"
OutFile "..\dist\FileMind_0.1.0_x64-setup.exe"
RequestExecutionLevel user

; Interface Settings
!define MUI_ABORTWARNING
!define MUI_ICON "..\src-tauri\icons\icon.ico"
!define MUI_UNICON "..\src-tauri\icons\icon.ico"

; Pages
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "English"

Function .onInit
  ${If} $INSTDIR == ""
    StrCpy $INSTDIR "$LOCALAPPDATA\Programs\FileMind"
  ${EndIf}
FunctionEnd

Section "MainSection" SEC01
  SetOutPath "$INSTDIR"
  SetOverwrite ifnewer

  ; Tauri Shell Executable & Runtime Libraries
  SetOutPath "$INSTDIR"
  File "..\src-tauri\target\release\FileMind.exe"
  File "..\src-tauri\target\release\WebView2Loader.dll"

  ; Bundled Standalone Python FastAPI Backend (unpacked sidecar onedir)
  ; The ONEDIR layout requires filemind-backend-dir.exe and _internal/ to be adjacent.
  SetOutPath "$INSTDIR\binaries\filemind-backend-dir"
  File /r "..\backend\dist\filemind-backend-dir\*.*"
  
  ; Bundled Frontend Distribution Assets
  SetOutPath "$INSTDIR\frontend"
  File /r "..\frontend\dist\*.*"
  
  ; Application Icon
  SetOutPath "$INSTDIR"
  File "..\src-tauri\icons\icon.ico"

  ; Create Shortcuts
  CreateDirectory "$SMPROGRAMS\FileMind"
  CreateShortcut "$SMPROGRAMS\FileMind\FileMind.lnk" "$INSTDIR\FileMind.exe" "" "$INSTDIR\icon.ico" 0
  CreateShortcut "$SMPROGRAMS\FileMind\Uninstall FileMind.lnk" "$INSTDIR\Uninstall.exe"
  CreateShortcut "$DESKTOP\FileMind.lnk" "$INSTDIR\FileMind.exe" "" "$INSTDIR\icon.ico" 0

  ; Write Uninstaller
  WriteUninstaller "$INSTDIR\Uninstall.exe"

  ; Registry keys for Add/Remove Programs
  WriteRegStr HKCU "${PRODUCT_DIR_REGKEY}" "" "$INSTDIR\FileMind.exe"
  WriteRegStr HKCU "${PRODUCT_UNINST_KEY}" "DisplayName" "${PRODUCT_NAME}"
  WriteRegStr HKCU "${PRODUCT_UNINST_KEY}" "UninstallString" "$INSTDIR\Uninstall.exe"
  WriteRegStr HKCU "${PRODUCT_UNINST_KEY}" "DisplayIcon" "$INSTDIR\icon.ico"
  WriteRegStr HKCU "${PRODUCT_UNINST_KEY}" "DisplayVersion" "${PRODUCT_VERSION}"
  WriteRegStr HKCU "${PRODUCT_UNINST_KEY}" "Publisher" "${PRODUCT_PUBLISHER}"
SectionEnd

Section "Uninstall"
  ; Terminate running processes if any
  nsExec::Exec 'taskkill /F /IM FileMind.exe'
  nsExec::Exec 'taskkill /F /IM filemind-backend.exe'
  nsExec::Exec 'taskkill /F /IM filemind-backend-dir.exe'
  Sleep 500

  ; Remove shortcuts
  Delete "$SMPROGRAMS\FileMind\FileMind.lnk"
  Delete "$SMPROGRAMS\FileMind\Uninstall FileMind.lnk"
  RMDir "$SMPROGRAMS\FileMind"
  Delete "$DESKTOP\FileMind.lnk"

  ; Remove installed files
  RMDir /r "$INSTDIR\binaries\filemind-backend-dir"
  RMDir "$INSTDIR\binaries"
  RMDir /r "$INSTDIR\frontend"
  Delete "$INSTDIR\FileMind.exe"
  Delete "$INSTDIR\WebView2Loader.dll"
  Delete "$INSTDIR\icon.ico"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"

  ; Remove registry keys
  DeleteRegKey HKCU "${PRODUCT_UNINST_KEY}"
  DeleteRegKey HKCU "${PRODUCT_DIR_REGKEY}"
SectionEnd
