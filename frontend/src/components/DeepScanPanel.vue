<template>
  <div class="deep-scan-panel">
    <h3>Deep Scan</h3>
    <div v-if="!device.deep_scan_enabled">Deep scan is disabled for this device.</div>
    <div v-else>
      <p>Profile: {{ device.deep_scan_profile }}</p>
      <p>Credential: {{ device.deep_scan_credential_name || '—' }}</p>
      <button @click="runScan" :disabled="running">Run Deep Scan</button>
      <div v-if="running">Planning...</div>
      <div v-if="lastRun">
        <h4>Last Run</h4>
        <p>Status: {{ lastRun.status }}</p>
        <pre v-if="lastRun.result">{{ JSON.stringify(lastRun.result, null, 2) }}</pre>
      </div>
      <div v-if="runs && runs.length">
        <h4>Recent Runs</h4>
        <ul>
          <li v-for="r in runs" :key="r.id">#{{ r.id }} — {{ r.status }} — {{ r.started_at }}</li>
        </ul>
      </div>
    </div>
  </div>
</template>

<script lang="ts">
import { defineComponent, ref, onMounted } from 'vue'
import type { Device } from '../api/devices'
import { devicesApi } from '../api/devices'

export default defineComponent({
  name: 'DeepScanPanel',
  props: {
    device: { type: Object as () => Device, required: true },
  },
  setup(props) {
    const runs = ref<Array<any>>([])
    const running = ref(false)
    const lastRun = ref<any | null>(null)

    async function loadRuns() {
      try {
        runs.value = await devicesApi.getDeepScanRuns(props.device.id)
        lastRun.value = runs.value.length ? runs.value[0] : null
      } catch (e) {
        console.error('Failed loading deep scan runs', e)
      }
    }

    async function runScan() {
      running.value = true
      try {
        const res = await devicesApi.runDeepScan(props.device.id)
        await loadRuns()
      } catch (e) {
        console.error('Run failed', e)
      } finally {
        running.value = false
      }
    }

    onMounted(() => {
      loadRuns()
    })

    return { runs, running, runScan, lastRun }
  },
})
</script>

<style scoped>
.deep-scan-panel { border: 1px solid #e5e7eb; padding: 12px; border-radius: 6px; }
</style>
