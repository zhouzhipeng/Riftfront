import { defineMaterial } from "@gdevelop/tsl";
import {
  abs,
  max,
  mix,
  normalLocal,
  oneMinus,
  positionLocal,
  sin,
  smoothstep,
  time,
  uv
} from "three/tsl";

export default defineMaterial({
  apiVersion: 1,
  base: "inherit",
  label: "Water surface",
  description: "Animated TSL pool water with layered caustic ribbons and subtle surface motion.",
  parameters: {
    deepColor: {
      type: "color",
      default: "#052E67",
      label: "Deep water color"
    },
    shallowColor: {
      type: "color",
      default: "#0C78BC",
      label: "Water blue"
    },
    highlightColor: {
      type: "color",
      default: "#9BE5F5",
      label: "Caustic highlight"
    },
    colorStrength: {
      type: "number",
      default: 0.98,
      min: 0,
      max: 1,
      label: "Water tint"
    },
    waveScale: {
      type: "number",
      default: 18.5,
      min: 0,
      max: 30,
      label: "Caustic scale"
    },
    waveSpeed: {
      type: "number",
      default: 0.75,
      min: -20,
      max: 20,
      label: "Caustic speed"
    },
    distortionScale: {
      type: "number",
      default: 10,
      min: 0,
      max: 30,
      label: "Caustic distortion scale"
    },
    distortionAmount: {
      type: "number",
      default: 1.15,
      min: 0,
      max: 5,
      label: "Caustic distortion"
    },
    lineWidth: {
      type: "number",
      default: 0.09,
      min: 0.01,
      max: 0.5,
      label: "Highlight line width"
    },
    highlightStrength: {
      type: "number",
      default: 0.78,
      min: 0,
      max: 2,
      label: "Highlight strength"
    },
    vertexScale: {
      type: "number",
      default: 0.08,
      min: 0,
      max: 1,
      label: "Vertex wave scale"
    },
    vertexAmplitude: {
      type: "number",
      default: 0.24,
      min: 0,
      max: 10,
      label: "Vertex wave height"
    },
    opacity: {
      type: "number",
      default: 0.92,
      min: 0.1,
      max: 1,
      label: "Water opacity"
    },
    emissiveStrength: {
      type: "number",
      default: 0.3,
      min: 0,
      max: 2,
      label: "Surface glow"
    },
    roughness: {
      type: "number",
      default: 0.22,
      min: 0,
      max: 1,
      label: "Roughness"
    },
    metalness: {
      type: "number",
      default: 0.03,
      min: 0,
      max: 1,
      label: "Metalness"
    }
  },
  build({ material, inputs, parameters }) {
    const vertexWave = sin(
      positionLocal.x.mul(parameters.vertexScale).add(time.mul(parameters.waveSpeed))
    ).add(
      sin(
        positionLocal.y
          .mul(parameters.vertexScale.mul(1.21))
          .sub(time.mul(parameters.waveSpeed.mul(0.61)))
      )
    );
    const displacement = vertexWave.mul(parameters.vertexAmplitude);

    const coordinates = uv();
    const phase = time.mul(parameters.waveSpeed);
    const warpedU = coordinates.x
      .mul(parameters.waveScale)
      .add(
        sin(
          coordinates.y
            .mul(parameters.distortionScale)
            .add(phase.mul(0.37))
        ).mul(parameters.distortionAmount)
      )
      .add(phase.mul(0.22));
    const warpedV = coordinates.y
      .mul(parameters.waveScale.mul(0.92))
      .add(
        sin(
          coordinates.x
            .mul(parameters.distortionScale.mul(1.13))
            .sub(phase.mul(0.31))
        ).mul(parameters.distortionAmount)
      )
      .sub(phase.mul(0.18));
    const warpedDiagonal = coordinates.x
      .add(coordinates.y)
      .mul(parameters.waveScale.mul(0.72))
      .add(
        sin(
          coordinates.x
            .sub(coordinates.y)
            .mul(parameters.distortionScale)
            .add(phase.mul(0.27))
        ).mul(parameters.distortionAmount.mul(0.65))
      )
      .add(phase.mul(0.14));

    const fieldA = sin(warpedU);
    const fieldB = sin(warpedV);
    const fieldC = sin(warpedDiagonal);
    const lineA = oneMinus(
      smoothstep(0, parameters.lineWidth, abs(fieldA))
    );
    const lineB = oneMinus(
      smoothstep(0, parameters.lineWidth, abs(fieldB))
    );
    const lineC = oneMinus(
      smoothstep(0, parameters.lineWidth.mul(0.8), abs(fieldC))
    );
    const caustic = max(lineA, max(lineB.mul(0.82), lineC.mul(0.68))).saturate();
    const broadVariation = fieldA
      .mul(0.15)
      .add(fieldB.mul(0.13))
      .add(fieldC.mul(0.08))
      .add(0.5)
      .saturate();
    const baseWaterColor = mix(
      parameters.deepColor,
      parameters.shallowColor,
      broadVariation
    );
    const highlightAmount = caustic
      .mul(parameters.highlightStrength)
      .saturate();
    const waterColor = mix(
      baseWaterColor,
      parameters.highlightColor,
      highlightAmount
    );

    material.positionNode = positionLocal.add(normalLocal.mul(displacement));
    material.colorNode = mix(inputs.baseColor, waterColor, parameters.colorStrength);
    material.emissiveNode = inputs.emissive.add(
      parameters.highlightColor
        .mul(highlightAmount)
        .mul(parameters.emissiveStrength)
    );
    material.opacityNode = inputs.opacity.mul(parameters.opacity);
    material.roughnessNode = parameters.roughness;
    material.metalnessNode = parameters.metalness;
    material.transparent = true;
    material.depthWrite = false;
    material.side = "double";
  }
});
