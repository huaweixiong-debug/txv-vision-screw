"""部署测试面板到目标工控机并启动"""
import paramiko
import sys
import time

HOST = "100.79.19.71"
USER = "a"
PASS = "0000"
REMOTE_DIR = "C:\\Users\\A\\kilews_panel"
LOCAL_FILE = __file__.replace("deploy_and_run.py", "kilews_test_panel.py")


def main():
    print("连接目标工控机...")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASS, timeout=10)
    print("已连接")

    # 创建远程目录
    client.exec_command("mkdir " + REMOTE_DIR + " 2>nul || echo ok", timeout=5)

    # 上传测试面板
    print("上传 kilews_test_panel.py ...")
    sftp = client.open_sftp()
    remote_path = REMOTE_DIR + "\\kilews_test_panel.py"
    sftp.put(LOCAL_FILE, remote_path)
    sftp.close()
    print("上传完成")

    # 检查目标工控机能访问拧紧枪
    print("\n--- 检查拧紧枪连通性 ---")
    stdin, stdout, stderr = client.exec_command(
        'ping -n 1 192.168.0.105 && echo PING_OK || echo PING_FAIL',
        timeout=10
    )
    for line in stdout:
        print("  " + line.rstrip())

    # 后台启动测试面板
    print("\n启动测试面板 (后台运行)...")
    client.exec_command(
        'start /B python "' + remote_path + '" > C:\\Users\\A\\kilews_panel\\stdout.log 2>&1',
        timeout=5,
    )
    time.sleep(2)

    # 检查是否启动成功
    stdin, stdout, stderr = client.exec_command(
        'netstat -an | findstr 8090',
        timeout=5,
    )
    result = stdout.read().decode().strip()
    if result:
        print("测试面板已启动! 端口 8090 监听中")
    else:
        print("可能启动失败，检查日志:")
        stdin, stdout, stderr = client.exec_command(
            'type C:\\Users\\A\\kilews_panel\\stdout.log',
            timeout=5,
        )
        print(stdout.read().decode())

    print("\n" + "=" * 50)
    print("测试面板地址: http://192.168.0.99:8090")
    print("(目标工控机本机: http://127.0.0.1:8090)")
    print("=" * 50)

    client.close()


if __name__ == "__main__":
    main()
