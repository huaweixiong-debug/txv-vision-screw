import paramiko, sys

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("100.79.19.71", username="a", password="0000", timeout=10)

cmd = 'findstr /C:"SKIP NG" C:\\Users\\A\\expansion_valve_hmi\\app\\workflow.py'
i, o, e = c.exec_command(cmd, timeout=5)

stdout = o.read()
stderr = e.read()
exit_code = o.channel.recv_exit_status()

# Use latin-1 which can round-trip any byte
sys.stdout.buffer.write(b"--- STDOUT ---\n")
sys.stdout.buffer.write(stdout)
sys.stdout.buffer.write(b"\n--- STDERR ---\n")
sys.stdout.buffer.write(stderr)
sys.stdout.buffer.write(b"\n--- EXIT: " + str(exit_code).encode() + b" ---\n")

c.close()
