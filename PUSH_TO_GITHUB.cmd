@echo off
echo =============================================
echo  Push Long Form Video Generator to GitHub
echo =============================================
echo.

REM Step 1: Authenticate GitHub CLI
echo [1/3] Authenticating with GitHub...
gh auth login --web --git-protocol https
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: GitHub authentication failed. Please try again.
    pause
    exit /b 1
)

echo.

REM Step 2: Create private repository
echo [2/3] Creating private repository on GitHub...
gh repo create long-form-video-generator --private --source=. --remote=origin --description="Focus Protocol Long Form Jazz Video Generator - FFmpeg pipeline with Flask dashboard"
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Repository creation failed. It may already exist.
    echo Trying to add remote manually...
    for /f "tokens=*" %%u in ('gh api user -q .login') do set GITHUB_USER=%%u
    git remote add origin https://github.com/%GITHUB_USER%/long-form-video-generator.git 2>nul
)

echo.

REM Step 3: Push code
echo [3/3] Pushing code to GitHub...
git push -u origin master
if %ERRORLEVEL% NEQ 0 (
    echo Trying main branch...
    git branch -M main
    git push -u origin main
)

echo.
echo =============================================
echo  DONE! Your code is now on GitHub.
echo  Check: https://github.com/YOUR_USERNAME/long-form-video-generator
echo =============================================
pause
