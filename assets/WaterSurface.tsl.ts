import { defineMaterial } from "@gdevelop/tsl";
import {
  mix,
  normalLocal,
  positionLocal,
  sin,
  time,
  uv
} from "three/tsl";

export default defineMaterial({
  apiVersion: 1,
  base: "inherit",
  label: "Water surface",
  description: "Animated TSL water with moving ripples and a subtle vertex wave.",
  parameters: {
    deepColor: {
      type: "color",
      default: "#063B60",
      label: "Deep water color"
    },
    shallowColor: {
      type: "color",
      default: "#59F3E8",
      label: "Highlight color"
    },
    colorStrength: {
      type: "number",
      default: 0.9,
      min: 0,
      max: 1,
      label: "Water tint"
    },
    waveScale: {
      type: "number",
      default: 7,
      min: 0,
      max: 30,
      label: "Ripple scale"
    },
    waveSpeed: {
      type: "number",
      default: 1.6,
      min: -20,
      max: 20,
      label: "Ripple speed"
    },
    vertexScale: {
      type: "number",
      default: 0.12,
      min: 0,
      max: 1,
      label: "Vertex wave scale"
    },
    vertexAmplitude: {
      type: "number",
      default: 1.4,
      min: 0,
      max: 10,
      label: "Vertex wave height"
    },
    opacity: {
      type: "number",
      default: 0.82,
      min: 0.1,
      max: 1,
      label: "Water opacity"
    },
    emissiveStrength: {
      type: "number",
      default: 0.35,
      min: 0,
      max: 2,
      label: "Surface glow"
    },
    roughness: {
      type: "number",
      default: 0.12,
      min: 0,
      max: 1,
      label: "Roughness"
    },
    metalness: {
      type: "number",
      default: 0.05,
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
    const waveA = sin(
      coordinates.x.mul(parameters.waveScale).add(time.mul(parameters.waveSpeed))
    )
      .mul(0.5)
      .add(0.5);
    const waveB = sin(
      coordinates.y
        .mul(parameters.waveScale.mul(1.37))
        .sub(time.mul(parameters.waveSpeed.mul(0.73)))
    )
      .mul(0.5)
      .add(0.5);
    const ripple = waveA.mul(0.6).add(waveB.mul(0.4));
    const waterColor = mix(parameters.deepColor, parameters.shallowColor, ripple);

    material.positionNode = positionLocal.add(normalLocal.mul(displacement));
    material.colorNode = mix(inputs.baseColor, waterColor, parameters.colorStrength);
    material.emissiveNode = inputs.emissive.add(
      waterColor.mul(ripple).mul(parameters.emissiveStrength)
    );
    material.opacityNode = inputs.opacity.mul(parameters.opacity);
    material.roughnessNode = parameters.roughness;
    material.metalnessNode = parameters.metalness;
    material.transparent = true;
    material.depthWrite = false;
    material.side = "double";
  }
});
