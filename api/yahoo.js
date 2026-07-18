/* Vercel serverless function — Yahoo Finance proxy */
module.exports = async (req, res) => {
  const { symbol, interval = '5m', range = '1d' } = req.query;

  if (!symbol) {
    return res.status(400).json({ error: 'missing symbol' });
  }

  res.setHeader('Access-Control-Allow-Origin', '*');

  try {
    const url = `https://query1.finance.yahoo.com/v8/finance/chart/${symbol}?interval=${interval}&range=${range}`;
    const response = await fetch(url, { headers: { 'User-Agent': 'Mozilla/5.0' } });
    const data = await response.json();
    return res.status(200).json(data);
  } catch (e) {
    return res.status(502).json({ error: e.message });
  }
};
