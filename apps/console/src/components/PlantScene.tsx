/**
 * Live 3D view of the line.
 *
 * Geometry is driven entirely by the plant registry - positions, and for
 * vessels the actual configured diameter and volume - so the scene is at true
 * scale rather than decorative. Colour is health, the ring under an asset is
 * its alert state, and the beads moving along the pipes are throughput. An
 * operator should be able to point at the thing that is wrong.
 */

import { Grid, Html, OrbitControls } from '@react-three/drei'
import { Canvas, useFrame } from '@react-three/fiber'
import { Suspense, useMemo, useRef } from 'react'
import * as THREE from 'three'

import { healthColour } from '../lib/format'
import { useTwin } from '../state/useTwin'
import type { AssetInfo, AssetSnapshot } from '../lib/types'

const UP = new THREE.Vector3(0, 1, 0)

/** Vessel dimensions come from the config; machines use representative sizes. */
function vesselSize(info: AssetInfo): { radius: number; height: number } {
  const diameter = Number(info.design.diameter_m ?? 3)
  const volume = Number(info.design.volume_m3 ?? 40)
  const radius = Math.max(0.6, diameter / 2)
  return { radius, height: Math.max(1.5, volume / (Math.PI * radius * radius)) }
}

/**
 * Neutral painted steel for a healthy machine.
 *
 * Colouring every asset by health sounds helpful and is not: when the whole
 * line is green, green stops carrying information and the scene reads as
 * decoration. A real control room keeps the plant neutral and spends colour
 * only on the thing that needs attention, so that is what this does - steel
 * until health drops, then an increasingly hot tint plus an emissive glow.
 */
const STEEL = '#7c8ea3'

const STEEL_COLOUR = new THREE.Color(STEEL)

function bodyColour(health: number, standby: boolean): { colour: string; glow: number } {
  if (standby) return { colour: '#4b5768', glow: 0 }
  if (health >= 80) return { colour: STEEL, glow: 0.04 }
  // Blend steel *toward* the health ramp rather than snapping to it, so a
  // machine at 78 looks faintly off rather than identical to one at 30. The
  // deck band already carries the exact value for anyone who wants it.
  const severity = Math.min(1, (80 - health) / 55)
  const tinted = STEEL_COLOUR.clone().lerp(new THREE.Color(healthColour(health)), severity ** 0.75)
  return { colour: `#${tinted.getHexString()}`, glow: 0.08 + severity * 0.45 }
}

function AssetBody({ info, colour, glow }: { info: AssetInfo; colour: string; glow: number }) {
  const material = (
    <meshStandardMaterial
      color={colour}
      emissive={colour}
      emissiveIntensity={glow}
      roughness={0.48}
      metalness={0.62}
    />
  )

  switch (info.kind) {
    case 'tank': {
      const { radius, height } = vesselSize(info)
      return (
        <group position={[0, height / 2, 0]}>
          <mesh castShadow>
            <cylinderGeometry args={[radius, radius, height, 28]} />
            {material}
          </mesh>
          {/* Dished roof, flattened and capped against the shell height so a
              wide vessel does not end up looking like a mushroom. */}
          <mesh
            position={[0, height / 2, 0]}
            scale={[1, Math.min(0.34, (height * 0.22) / radius), 1]}
          >
            <sphereGeometry args={[radius, 28, 12, 0, Math.PI * 2, 0, Math.PI / 2]} />
            {material}
          </mesh>
        </group>
      )
    }
    case 'reactor': {
      return (
        <group position={[0, 2.4, 0]}>
          <mesh castShadow>
            <cylinderGeometry args={[1.7, 1.7, 3.6, 28]} />
            {material}
          </mesh>
          <mesh position={[0, 1.8, 0]} scale={[1, 0.55, 1]}>
            <sphereGeometry args={[1.7, 28, 12, 0, Math.PI * 2, 0, Math.PI / 2]} />
            {material}
          </mesh>
          <mesh position={[0, -1.8, 0]} rotation={[Math.PI, 0, 0]} scale={[1, 0.55, 1]}>
            <sphereGeometry args={[1.7, 28, 12, 0, Math.PI * 2, 0, Math.PI / 2]} />
            {material}
          </mesh>
        </group>
      )
    }
    case 'centrifugal_pump':
      return (
        <group position={[0, 0.5, 0]}>
          <mesh position={[0, -0.35, 0]}>
            <boxGeometry args={[2.6, 0.3, 1.5]} />
            <meshStandardMaterial color="#334155" roughness={0.9} metalness={0.2} />
          </mesh>
          {/* Volute */}
          <mesh position={[-0.75, 0.15, 0]} castShadow>
            <cylinderGeometry args={[0.62, 0.62, 0.55, 24]} />
            {material}
          </mesh>
          {/* Motor */}
          <mesh position={[0.65, 0.1, 0]} rotation={[0, 0, Math.PI / 2]} castShadow>
            <cylinderGeometry args={[0.42, 0.42, 1.5, 20]} />
            {material}
          </mesh>
        </group>
      )
    case 'heat_exchanger':
      return (
        <group position={[0, 1.1, 0]} rotation={[0, 0, Math.PI / 2]}>
          <mesh castShadow>
            <cylinderGeometry args={[0.85, 0.85, 5.2, 24]} />
            {material}
          </mesh>
          {[-2.6, 2.6].map((y) => (
            <mesh key={y} position={[0, y, 0]}>
              <cylinderGeometry args={[1.0, 1.0, 0.25, 24]} />
              <meshStandardMaterial color="#475569" metalness={0.6} roughness={0.4} />
            </mesh>
          ))}
        </group>
      )
    case 'separator':
      return (
        <group position={[0, 2.2, 0]}>
          <mesh castShadow>
            <cylinderGeometry args={[1.15, 1.15, 4.4, 24]} />
            {material}
          </mesh>
          <mesh position={[0, 2.2, 0]}>
            <coneGeometry args={[1.15, 0.9, 24]} />
            {material}
          </mesh>
        </group>
      )
    case 'chiller':
      return (
        <group position={[0, 1.2, 0]}>
          <mesh castShadow>
            <boxGeometry args={[4.2, 2.4, 2.6]} />
            {material}
          </mesh>
          {/* Condenser coils */}
          {[-1.3, 0, 1.3].map((x) => (
            <mesh key={x} position={[x, 1.35, 0]}>
              <cylinderGeometry args={[0.55, 0.55, 0.22, 20]} />
              <meshStandardMaterial color="#1e293b" metalness={0.7} roughness={0.35} />
            </mesh>
          ))}
        </group>
      )
    case 'compressor':
      return (
        <group position={[0, 1.0, 0]}>
          <mesh castShadow>
            <boxGeometry args={[3.4, 2.0, 1.9]} />
            {material}
          </mesh>
          <mesh position={[0, 1.35, 0]} rotation={[0, 0, Math.PI / 2]}>
            <cylinderGeometry args={[0.45, 0.45, 2.4, 20]} />
            {material}
          </mesh>
        </group>
      )
    case 'gearbox':
      return (
        <mesh position={[0, 0.6, 0]} castShadow>
          <boxGeometry args={[1.5, 1.2, 1.2]} />
          {material}
        </mesh>
      )
    default:
      return (
        <mesh position={[0, 1, 0]} castShadow>
          <boxGeometry args={[2, 2, 2]} />
          {material}
        </mesh>
      )
  }
}

function AlertRing({ colour, radius }: { colour: string; radius: number }) {
  const ref = useRef<THREE.Mesh>(null)
  useFrame(({ clock }) => {
    if (!ref.current) return
    // Slow breathing scale - noticeable in peripheral vision without being
    // the kind of strobe that gets a monitor turned off.
    const t = (clock.elapsedTime % 2) / 2
    const scale = 1 + t * 0.85
    ref.current.scale.set(scale, scale, scale)
    const material = ref.current.material as THREE.MeshBasicMaterial
    material.opacity = 0.55 * (1 - t)
  })
  return (
    <mesh ref={ref} rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.06, 0]}>
      <ringGeometry args={[radius, radius + 0.22, 48]} />
      <meshBasicMaterial color={colour} transparent opacity={0.5} side={THREE.DoubleSide} />
    </mesh>
  )
}

function Asset({
  info,
  snapshot,
  selected,
  onSelect,
}: {
  info: AssetInfo
  snapshot: AssetSnapshot | undefined
  selected: boolean
  onSelect: (id: string) => void
}) {
  const health = snapshot?.health ?? 100
  const standby = snapshot?.state === 'standby'
  const { colour, glow } = bodyColour(health, standby)
  const alerting = (snapshot?.open_alerts ?? 0) > 0
  const footprint = info.kind === 'tank' ? vesselSize(info).radius + 0.5 : 2.0

  return (
    <group
      position={info.position}
      onClick={(event) => {
        event.stopPropagation()
        onSelect(info.id)
      }}
      onPointerOver={(event) => {
        event.stopPropagation()
        document.body.style.cursor = 'pointer'
      }}
      onPointerOut={() => {
        document.body.style.cursor = 'auto'
      }}
    >
      <AssetBody info={info} colour={colour} glow={glow} />

      {/* Health band on the deck: one consistent place to read condition,
          regardless of what shape the machine above it happens to be. */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.02, 0]}>
        <ringGeometry args={[footprint - 0.3, footprint - 0.06, 40]} />
        <meshBasicMaterial
          color={standby ? '#475569' : healthColour(health)}
          transparent
          opacity={0.75}
          side={THREE.DoubleSide}
        />
      </mesh>

      {selected && (
        <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.04, 0]}>
          <ringGeometry args={[footprint, footprint + 0.16, 48]} />
          <meshBasicMaterial color="#22d3ee" side={THREE.DoubleSide} />
        </mesh>
      )}
      {alerting && <AlertRing colour={snapshot!.health < 40 ? '#fb7185' : '#fbbf24'} radius={footprint} />}

      <Html position={[0, info.kind === 'gearbox' ? 1.9 : 0, 0]} center zIndexRange={[20, 0]}>
        <button
          onClick={(event) => {
            event.stopPropagation()
            onSelect(info.id)
          }}
          className={`-translate-y-[60px] whitespace-nowrap rounded-md border px-1.5 py-0.5 text-[10px] font-semibold
            backdrop-blur-sm transition ${
              selected
                ? 'border-accent bg-accent/20 text-accent'
                : 'border-line/80 bg-ink-900/75 text-slate-300 hover:border-accent-dim'
            }`}
        >
          <span className="num">{info.id}</span>
          {alerting && <span className="ml-1 text-crit">&#9679;</span>}
        </button>
      </Html>
    </group>
  )
}

/** A pipe run between two assets, with beads whose speed tracks throughput. */
function Pipe({
  from,
  to,
  rate,
}: {
  from: [number, number, number]
  to: [number, number, number]
  rate: number
}) {
  const beads = useRef<THREE.InstancedMesh>(null)
  const dummy = useMemo(() => new THREE.Object3D(), [])

  const { position, quaternion, length, start, direction } = useMemo(() => {
    const a = new THREE.Vector3(from[0], 1.1, from[2])
    const b = new THREE.Vector3(to[0], 1.1, to[2])
    const delta = new THREE.Vector3().subVectors(b, a)
    const len = delta.length()
    const dir = delta.clone().normalize()
    return {
      position: new THREE.Vector3().addVectors(a, b).multiplyScalar(0.5),
      quaternion: new THREE.Quaternion().setFromUnitVectors(UP, dir),
      length: len,
      start: a,
      direction: dir,
    }
  }, [from, to])

  const COUNT = 4
  useFrame(({ clock }) => {
    if (!beads.current) return
    const speed = 0.08 + rate * 0.9
    for (let i = 0; i < COUNT; i += 1) {
      const progress = ((clock.elapsedTime * speed + i / COUNT) % 1) * length
      dummy.position.copy(start).addScaledVector(direction, progress)
      dummy.updateMatrix()
      beads.current.setMatrixAt(i, dummy.matrix)
    }
    beads.current.instanceMatrix.needsUpdate = true
  })

  return (
    <group>
      <mesh position={position} quaternion={quaternion}>
        <cylinderGeometry args={[0.16, 0.16, length, 12]} />
        <meshStandardMaterial color="#334155" metalness={0.8} roughness={0.35} />
      </mesh>
      <instancedMesh ref={beads} args={[undefined, undefined, COUNT]}>
        <sphereGeometry args={[0.13, 10, 10]} />
        <meshBasicMaterial color="#22d3ee" transparent opacity={0.85} />
      </instancedMesh>
    </group>
  )
}

function Scene({
  selected,
  onSelect,
}: {
  selected: string | null
  onSelect: (id: string | null) => void
}) {
  const { plant, frame } = useTwin()
  if (!plant) return null

  const byId = new Map(plant.assets.map((a) => [a.id, a]))
  // Normalised throughput drives bead speed, so the pipes visibly slow when
  // the line does.
  const rate = frame ? Math.min(1.4, frame.kpis.throughput_tph / plant.plant.design_rate_tph) : 0

  const pipes = plant.assets.flatMap((asset) =>
    asset.feeds
      .map((target) => byId.get(target))
      .filter((t): t is AssetInfo => Boolean(t))
      .map((target) => ({ key: `${asset.id}->${target.id}`, from: asset.position, to: target.position })),
  )

  return (
    <>
      <color attach="background" args={['#07090d']} />
      <fog attach="fog" args={['#07090d', 45, 105]} />

      <ambientLight intensity={0.55} />
      <directionalLight position={[18, 26, 14]} intensity={1.15} castShadow />
      <directionalLight position={[-16, 10, -12]} intensity={0.35} color="#38bdf8" />

      <Grid
        args={[90, 90]}
        cellSize={2}
        cellColor="#16202f"
        sectionSize={10}
        sectionColor="#1f3550"
        fadeDistance={78}
        fadeStrength={1.4}
        infiniteGrid
        position={[0, 0, 0]}
      />

      {pipes.map((pipe) => (
        <Pipe key={pipe.key} from={pipe.from} to={pipe.to} rate={rate} />
      ))}

      {plant.assets.map((asset) => (
        <Asset
          key={asset.id}
          info={asset}
          snapshot={frame?.assets[asset.id]}
          selected={selected === asset.id}
          onSelect={onSelect}
        />
      ))}

      <OrbitControls
        makeDefault
        enablePan
        minDistance={12}
        maxDistance={95}
        maxPolarAngle={Math.PI / 2.12}
        target={[1, 2.5, 1]}
      />
    </>
  )
}

export default function PlantScene({
  selected,
  onSelect,
  className = '',
}: {
  selected: string | null
  onSelect: (id: string | null) => void
  className?: string
}) {
  return (
    <div className={`relative ${className}`}>
      <Canvas
        shadows
        dpr={[1, 1.75]}
        camera={{ position: [-2, 19, 41], fov: 40 }}
        onPointerMissed={() => onSelect(null)}
      >
        <Suspense fallback={null}>
          <Scene selected={selected} onSelect={onSelect} />
        </Suspense>
      </Canvas>

      <div className="pointer-events-none absolute bottom-3 left-4 flex items-center gap-3 text-[10px] text-slate-600">
        <span>Drag to orbit &middot; scroll to zoom &middot; click an asset</span>
      </div>
      <div className="pointer-events-none absolute bottom-3 right-4 flex items-center gap-3 text-[10px]">
        {[
          ['#34d399', 'Healthy'],
          ['#fbbf24', 'Degrading'],
          ['#fb7185', 'At threshold'],
          ['#475569', 'Standby'],
        ].map(([colour, label]) => (
          <span key={label} className="flex items-center gap-1.5 text-slate-500">
            <span className="h-2 w-2 rounded-full" style={{ backgroundColor: colour }} />
            {label}
          </span>
        ))}
      </div>
    </div>
  )
}
