// Native credential lookup used by CodebuffAI/freebuff:
// cli/src/utils/auth-token-store.ts, resolveSecretStore.
const credentialsPath = process.argv[2];
if (!credentialsPath) throw new Error("Missing Freebuff credentials path");
const token = await Bun.secrets.get({
  service: "freebuff-cli",
  name: credentialsPath,
});
if (!token) throw new Error("Freebuff credential store has no token for this profile");
process.stdout.write(token);
