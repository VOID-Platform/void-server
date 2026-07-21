import express from 'express';
import cors from 'cors';
import { db } from './db';

const app = express();
const PORT = process.env.NODE_API_PORT || 3001;

app.use(cors());
app.use(express.json());

// Healthcheck endpoint verifying PostgreSQL database connection
app.get('/health', async (_req, res) => {
  try {
    await db.$queryRaw`SELECT 1`;
    res.json({ status: 'ok', service: 'node-api', database: 'connected' });
  } catch (error) {
    res.status(500).json({ status: 'error', database: 'disconnected', details: String(error) });
  }
});

// Fetch all incidents with associated reports
app.get('/api/incidents', async (_req, res) => {
  try {
    const incidents = await db.incident.findMany({
      include: { reports: true },
      orderBy: { created_at: 'desc' },
    });
    res.json({ count: incidents.length, data: incidents });
  } catch (error) {
    res.status(500).json({ error: 'Failed to fetch incidents', details: String(error) });
  }
});

// Create or update an incident
app.post('/api/incidents', async (req, res) => {
  try {
    const {
      fingerprint,
      trace_id,
      execution_id,
      title,
      severity,
      status,
      confidence,
      first_scene,
      last_scene,
    } = req.body;

    const incident = await db.incident.upsert({
      where: { fingerprint },
      update: {
        occurrence: { increment: 1 },
        last_scene,
        status,
      },
      create: {
        fingerprint,
        trace_id,
        execution_id,
        title,
        severity,
        status,
        confidence,
        first_scene,
        last_scene,
      },
    });

    res.status(201).json({ status: 'success', data: incident });
  } catch (error) {
    res.status(500).json({ error: 'Failed to save incident', details: String(error) });
  }
});

app.listen(PORT, () => {
  console.log(`🚀 Node.js API running at http://localhost:${PORT}`);
});
