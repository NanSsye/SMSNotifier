
import sys
import time
import os

# 监控错误文件路径
error_path = os.path.join(os.path.dirname(__file__), "heartbeat_errors.txt")

# 记录上次大小
last_size = 0
if os.path.exists(error_path):
    last_size = os.path.getsize(error_path)

while True:
    line = sys.stdin.readline()
    if not line:
        break
        
    # 检查是否有心跳失败
    if "Heartbeat failed" in line or "用户可能退出" in line:
        try:
            with open(error_path, "a") as f:
                f.write(f"stderr检测到心跳失败: {time.strftime('%Y-%m-%d %H:%M:%S')} - {line}")
        except:
            pass
            
    # 刷新到标准错误，以便原始日志系统仍能记录
    sys.stderr.write(line)
    sys.stderr.flush()
    
    # 休眠一小段时间减少CPU使用
    time.sleep(0.1)
