import { Account, Client, TablesDB } from 'node-appwrite';
import { ExportError, exportOrganization } from './exporter.mjs';

export function createHandler({ env = process.env,
  verifyActor = async ({ endpoint, project, jwt }) =>
    (await new Account(new Client().setEndpoint(endpoint).setProject(project).setJWT(jwt)).get()).$id,
  createDatabase = ({ endpoint, project, apiKey }) =>
    new TablesDB(new Client().setEndpoint(endpoint).setProject(project).setKey(apiKey)),
  exporter = exportOrganization } = {}) {
  return async function handler({ req, res, error = () => {} }) {
    if (req.method !== 'GET') return res.json({ error: 'METHOD_NOT_ALLOWED' }, 405);
    // Query parameters are not accepted: the organization always comes from
    // the verified caller's server-managed membership, never from user input.
    if (req.path !== '/export') return res.json({ error: 'NOT_FOUND' }, 404);
    const jwt = req.headers?.['x-appwrite-user-jwt'];
    if (!jwt) return res.json({ error: 'UNAUTHENTICATED' }, 401);
    const endpoint = env.APPWRITE_FUNCTION_API_ENDPOINT;
    const project = env.APPWRITE_FUNCTION_PROJECT_ID;
    const databaseId = env.APPWRITE_DATABASE_ID;
    const apiKey = req.headers?.['x-appwrite-key'];
    if (!endpoint || !project || !databaseId || !apiKey)
      return res.json({ error: 'CONFIGURATION_REQUIRED' }, 503);
    let actorId;
    try { actorId = await verifyActor({ endpoint, project, jwt }); }
    catch { return res.json({ error: 'UNAUTHENTICATED' }, 401); }
    if (typeof actorId !== 'string' || !actorId)
      return res.json({ error: 'UNAUTHENTICATED' }, 401);
    try {
      const db = createDatabase({ endpoint, project, apiKey });
      return res.json(await exporter({ db, databaseId, actorId }), 200);
    } catch (cause) {
      if (cause instanceof ExportError) return res.json({ error: cause.code, message: cause.message }, cause.status);
      // Keep account identifiers, credentials, database rows and SDK response
      // bodies out of logs and error responses.
      error('Read-only audit export failed. Check Function configuration and execution limits.');
      return res.json({ error: 'EXPORT_UNAVAILABLE' }, 503);
    }
  };
}

export default createHandler();
