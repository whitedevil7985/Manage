import httpx

class HerokuAPIError(RuntimeError):
    pass

class HerokuClient:
    BASE_URL = "https://api.heroku.com"

    def __init__(self, api_token: str):
        self._client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            headers={
                "Authorization": f"Bearer {api_token}",
                "Accept": "application/vnd.heroku+json; version=3",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(20.0, connect=10.0),
        )

    async def close(self):
        await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs):
        try:
            response = await self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise HerokuAPIError("Could not connect to Heroku. Please retry.") from exc
        if response.status_code >= 400:
            message = "Heroku API request failed."
            try:
                payload = response.json()
                message = payload.get("message") or payload.get("error") or message
            except ValueError:
                pass
            if response.status_code in (401, 403):
                message = "Heroku token is invalid or does not have permission."
            raise HerokuAPIError(f"{message} (HTTP {response.status_code})")
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    async def validate_token(self):
        return await self._request("GET", "/account")

    async def list_apps(self):
        return await self._request("GET", "/apps", params={"sort": "name"})

    async def get_app(self, app_name: str):
        return await self._request("GET", f"/apps/{app_name}")

    async def list_dynos(self, app_name: str):
        return await self._request("GET", f"/apps/{app_name}/dynos")

    async def get_config_vars(self, app_name: str):
        return await self._request("GET", f"/apps/{app_name}/config-vars")

    async def set_config_vars(self, app_name: str, values: dict):
        return await self._request("PATCH", f"/apps/{app_name}/config-vars", json=values)

    async def delete_config_var(self, app_name: str, key: str):
        return await self.set_config_vars(app_name, {key: None})

    async def restart_app(self, app_name: str):
        return await self._request("DELETE", f"/apps/{app_name}/dynos")
