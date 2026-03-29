import http.client
import json
from urllib.parse import urlparse


class InterfaceAPI:
    def __init__(self, api_endpoint, api_key, model_LLM, debug_mode, timeout_seconds=None):
        self.api_endpoint = api_endpoint
        self.api_key = api_key
        self.model_LLM = model_LLM
        self.debug_mode = debug_mode
        self.n_trial = 5
        self.timeout_seconds = timeout_seconds
        self.connection_class, self.connection_host, self.request_path = self._resolve_endpoint(api_endpoint)

    def _resolve_endpoint(self, api_endpoint):
        parsed = urlparse(api_endpoint)

        if parsed.scheme in ["http", "https"] and parsed.netloc:
            connection_class = (
                http.client.HTTPConnection if parsed.scheme == "http" else http.client.HTTPSConnection
            )
            connection_host = parsed.netloc
            base_path = parsed.path.rstrip("/")
            if base_path:
                request_path = base_path + "/chat/completions"
            else:
                request_path = "/v1/chat/completions"
            return connection_class, connection_host, request_path

        # Backward-compatible path: upstream code expected a bare host and always used HTTPS.
        return http.client.HTTPSConnection, api_endpoint, "/v1/chat/completions"

    def get_response(self, prompt_content):
        payload_explanation = json.dumps(
            {
                "model": self.model_LLM,
                "messages": [
                    # {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": prompt_content}
                ],
            }
        )

        headers = {
            "Authorization": "Bearer " + self.api_key,
            "User-Agent": "Apifox/1.0.0 (https://apifox.com)",
            "Content-Type": "application/json",
            "x-api2d-no-cache": 1,
        }
        
        response = None
        n_trial = 1
        while True:
            n_trial += 1
            if n_trial > self.n_trial:
                return response
            try:
                conn = self.connection_class(self.connection_host, timeout=self.timeout_seconds)
                conn.request("POST", self.request_path, payload_explanation, headers)
                res = conn.getresponse()
                data = res.read()
                json_data = json.loads(data)
                response = json_data["choices"][0]["message"]["content"]
                break
            except Exception:
                if self.debug_mode:
                    print("Error in API. Restarting the process...")
                continue
            

        return response
