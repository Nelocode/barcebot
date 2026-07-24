import subprocess, os, sys

# Usar encoding del sistema para evitar UnicodeDecodeError
result = subprocess.run(
    ["tasklist", "/FI", "IMAGENAME eq python.exe", "/FO", "CSV"],
    capture_output=True, timeout=10
)
# Decodificar con cp1252 (Windows latin-1)
stdout = result.stdout.decode("cp1252", errors="replace")
print(stdout)
