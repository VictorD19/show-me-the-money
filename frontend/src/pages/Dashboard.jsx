import { useState } from 'react'
import useWebSocket from '../hooks/useWebSocket'
import useApi from '../hooks/useApi'
import Sidebar from '../components/layout/Sidebar'
import TopBar from '../components/layout/TopBar'
import ChartPanel from '../components/chart/ChartPanel'
import PositionCard from '../components/cards/PositionCard'
import ModelCard from '../components/cards/ModelCard'
import MetricCard from '../components/cards/MetricCard'
import TradesTable from '../components/tables/TradesTable'
import MarketPanel from '../components/panels/MarketPanel'
import NewsPanel from '../components/panels/NewsPanel'
import EquityChart from '../components/panels/EquityChart'

export default function Dashboard() {
  const [activePage, setActivePage] = useState('dashboard')
  const [selectedSymbol] = useState('BTCUSDT')
  const { lastMessage, isConnected } = useWebSocket()
  const {
    balance,
    prices,
    trades,
    performance,
    modelInfo,
    news,
    fearGreed,
    openPositions,
  } = useApi()

  const openPosition = openPositions?.[0] || null
  const perf = performance || {}

  const wsData = lastMessage || {}
  const currentPrices = wsData.prices || prices

  const marketData = {
    fundingRates: wsData.fundingRates || {},
    openInterest: wsData.openInterest || {},
    regime: modelInfo?.regime || 'LATERAL',
  }

  return (
    <div className="flex h-screen bg-bg-primary overflow-hidden">
      <Sidebar active={activePage} onNavigate={setActivePage} />
      <div className="flex-1 flex flex-col overflow-hidden">
        <TopBar prices={currentPrices} isConnected={isConnected} />
        <main className="flex-1 overflow-auto p-4">
          <div className="grid grid-cols-12 gap-4">

            {/* Grafico - 8 colunas */}
            <div className="col-span-8 row-span-2 min-h-[400px]">
              <ChartPanel symbol={selectedSymbol} />
            </div>

            {/* Posicao aberta - 4 colunas */}
            <div className="col-span-4">
              <PositionCard position={openPosition} />
            </div>

            {/* Modelo ML - 4 colunas */}
            <div className="col-span-4">
              <ModelCard model={modelInfo} />
            </div>

            {/* Metricas do dia - 4 cards em linha */}
            <div className="col-span-8 grid grid-cols-4 gap-4">
              <MetricCard
                title="Win Rate"
                value={perf.winRate != null ? `${perf.winRate}%` : '71%'}
                trend="up"
              />
              <MetricCard
                title="Trades Hoje"
                value={perf.tradesToday ?? '7'}
                subtitle={perf.wl || '5W / 2L'}
              />
              <MetricCard
                title="Lucro Dia"
                value={perf.dailyProfit != null ? `${perf.dailyProfit >= 0 ? '+' : ''}$${perf.dailyProfit}` : '+$380'}
                trend={perf.dailyProfit >= 0 ? 'up' : 'down'}
                color={perf.dailyProfit >= 0 ? 'green' : 'red'}
              />
              <MetricCard
                title="Banca"
                value={balance?.total != null ? `$${Number(balance.total).toLocaleString()}` : '$10.000'}
                subtitle="Binance"
              />
            </div>

            {/* Tabela de trades - 8 colunas */}
            <div className="col-span-8">
              <TradesTable trades={trades} />
            </div>

            {/* Painel direito - 4 colunas */}
            <div className="col-span-4 flex flex-col gap-4">
              <MarketPanel data={marketData} balance={balance} />
              <NewsPanel news={news} fearGreed={fearGreed} />
              <EquityChart trades={trades} />
            </div>

          </div>
        </main>
      </div>
    </div>
  )
}
