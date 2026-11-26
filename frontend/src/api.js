// Seranın (Colorado) bugünkü tarihi, YYYY-MM-DD: günlük özetler Denver saatine göre gruplanır
export const denverToday = () => new Date().toLocaleDateString('en-CA', { timeZone: 'America/Denver' });
export const API = import.meta.env.VITE_API_URL || 'http://localhost:8000';
export const WS = API.replace(/^http/, 'ws');
