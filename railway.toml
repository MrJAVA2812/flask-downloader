# railway.toml

[build]
  command = "pip install -r requirements.txt"

[start]
  command = "python app.py"
  env = "production"
  healthcheck_path = "/health"

[deploy]
  restart = true
  sleep = false
