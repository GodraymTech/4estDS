import sys
import faulthandler
faulthandler.enable()

try:
    import uvicorn
    from forestds.api.main import app
    print("Import successful. Starting uvicorn...")
    uvicorn.run(app)
except Exception as e:
    print(f"Exception: {e}", file=sys.stderr)
