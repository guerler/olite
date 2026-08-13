from .http import http

from .exceptions import ConfigurationError, ProviderError
from .api import API_METHODS, ApiOp, ApiProvider, ApiTarget
from .openapi_ops import openapi_get, openapi_post
from .openapi import OpenApiCatalog

ALLOWED_METHODS = [API_METHODS.GET, API_METHODS.POST]

# Targeted write allowlist: which POST ops may be reached at all (by catalog op
WRITE_ALLOWLIST = {
    "tools.post",  # run_tool
    "histories.post",  # create_history
}
PROVIDER_NAME = "galaxy"
# Prefix allowlist scopes what the agent can reach. Widened past polaris's read
PREFIXES = [
    "/api/histories",
    "/api/datasets",
    "/api/dataset_collections",
    "/api/jobs",
    "/api/tools",
    "/api/workflows",
    "/api/invocations",
    "/api/pages",
    "/api/users",
    "/api/configuration",
    "/api/version",
    "/api/whoami",
]
DUMP_ENDPOINTS_PATH = None  # Set to a file path to dump discovered endpoints


class GalaxyApi(ApiProvider):
    def __init__(self, config):
        self.galaxy_root = config.get("galaxy_root")
        if not self.galaxy_root:
            raise ConfigurationError("galaxy_root missing")

        self.galaxy_key = config.get("galaxy_key")
        self.openapi = None

    async def init(self):
        url = f"{self.galaxy_root}openapi.json"
        try:
            spec = await http.request("GET", url)
            self.openapi = OpenApiCatalog(
                spec=spec,
                prefixes=PREFIXES,
                methods=ALLOWED_METHODS,
                dump_path=DUMP_ENDPOINTS_PATH,
            )
        except Exception as e:
            raise ProviderError(f"Failed to load OpenAPI schema from {url}: {e}") from e
        return self

    def target(self):
        return ApiTarget(
            name=PROVIDER_NAME,
            base_url=self.galaxy_root,
            headers=self._galaxy_headers,
        )

    def ops(self):
        return {}

    def resolve_op(self, name):
        prefix = f"{PROVIDER_NAME}."
        if not name.startswith(prefix):
            return None
        if self.openapi is None:
            return None
        local = name[len(prefix) :]
        resolved = self.openapi.get_op(local)
        if not resolved:
            return None
        path, operation, method = resolved
        if method == API_METHODS.GET:
            handler, capability = openapi_get, "read"
        elif method == API_METHODS.POST:
            # Writes are targeted: only allowlisted POST ops resolve at all.
            if local not in WRITE_ALLOWLIST:
                return None
            handler, capability = openapi_post, "write"
        else:
            return None
        return ApiOp(
            target="galaxy",
            handler=handler,
            capability=capability,
            meta={
                "path": path,
                "operation": operation,
                "method": method,
            },
        )

    def _galaxy_headers(self):
        if self.galaxy_key:
            return {"x-api-key": self.galaxy_key}
        return {}
