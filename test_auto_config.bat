@echo off
REM 测试自动配置脚本

echo ========================================
echo   测试 AutoConfig
echo ========================================
echo.

REM 设置PYTHONPATH
set PYTHONPATH=%CD%\src

REM 运行检测
python -m src.anima.utils.auto_config --check

echo.
echo ========================================
echo   测试完成
echo ========================================
pause
