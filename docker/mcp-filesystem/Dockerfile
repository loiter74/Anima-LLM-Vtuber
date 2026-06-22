FROM node:22-alpine

# Install MCP filesystem server
RUN npm install -g @modelcontextprotocol/server-filesystem

# Non-root user
RUN adduser -D -s /bin/sh mcp
USER mcp

WORKDIR /data

# The server's allowed directory is passed as CMD argument
ENTRYPOINT ["mcp-server-filesystem"]
CMD ["/data"]
