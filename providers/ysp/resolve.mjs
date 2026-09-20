import { requestPlayUrls, selectWorkingManifest } from './api.mjs'

const CHANNELS = {
  cctv1: ['2024078201', '600001859', 'fhd'],
  cctv2: ['2024075401', '600001800', 'fhd'],
  cctv3: ['2024068501', '600001801', 'fhd'],
  cctv4: ['2029797101', '600001814', 'fhd'],
  cctv5: ['2024078401', '600001818', 'fhd'],
  cctv5plus: ['2024078001', '600001817', 'fhd'],
  cctv6: ['2013693901', '600108442', 'fhd'],
  cctv7: ['2024072001', '600004092', 'fhd'],
  cctv8: ['2029793001', '600001803', 'fhd'],
  cctv9: ['2024078601', '600004078', 'fhd'],
  cctv10: ['2024078701', '600001805', 'fhd'],
  cctv11: ['2027248701', '600001806', 'fhd'],
  cctv12: ['2027248801', '600001807', 'fhd'],
  cctv13: ['2029797201', '600001811', 'fhd'],
  cctv14: ['2027248901', '600001809', 'fhd'],
  cctv15: ['2027249001', '600001815', 'fhd'],
  cctv16: ['2027249101', '600098637', 'fhd'],
  cctv17: ['2027249401', '600001810', 'fhd'],
}

const id = process.argv[2]
const raw = CHANNELS[id]
if (!raw) {
  console.error('unknown channel')
  process.exit(2)
}

const channel = { livePid: raw[0], channelId: raw[1], defn: raw[2] }

try {
  const { urls } = await requestPlayUrls(channel)
  const manifest = await selectWorkingManifest(urls)
  process.stdout.write(manifest.url + '\n')
} catch (error) {
  console.error(error?.message || String(error))
  process.exit(1)
}
