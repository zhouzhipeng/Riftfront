import { defineMaterial } from "@gdevelop/tsl";
import {
  fract,
  mix,
  normalLocal,
  positionLocal,
  sin,
  smoothstep,
  texture,
  time,
  uv,
  vec2,
  vec3
} from "three/tsl";

export default defineMaterial({
  apiVersion: 1,
  base: "inherit",
  label: "Water surface",
  description: "Animated pool water using a generated caustic base texture with layered UV drift.",
  parameters: {
    causticTexture: {
      type: "texture",
      default: "WaterCausticsBase",
      colorSpace: "srgb",
      label: "Caustic base texture"
    },
    deepColor: {
      type: "color",
      default: "#032F68",
      label: "Deep water color"
    },
    shallowColor: {
      type: "color",
      default: "#0A82C8",
      label: "Water blue"
    },
    highlightColor: {
      type: "color",
      default: "#B9F2FF",
      label: "Caustic highlight"
    },
    textureStrength: {
      type: "number",
      default: 0.88,
      min: 0,
      max: 1,
      label: "Texture influence"
    },
    colorStrength: {
      type: "number",
      default: 0.96,
      min: 0,
      max: 1,
      label: "Water tint"
    },
    textureScale: {
      type: "number",
      default: 1.1,
      min: 0.25,
      max: 4,
      label: "Texture tiling"
    },
    waveSpeed: {
      type: "number",
      default: 0.55,
      min: -20,
      max: 20,
      label: "Water drift speed"
    },
    distortionScale: {
      type: "number",
      default: 9,
      min: 0,
      max: 30,
      label: "UV distortion scale"
    },
    distortionAmount: {
      type: "number",
      default: 0.065,
      min: 0,
      max: 0.5,
      label: "UV distortion amount"
    },
    highlightThreshold: {
      type: "number",
      default: 0.62,
      min: 0,
      max: 1,
      label: "Highlight threshold"
    },
    highlightSoftness: {
      type: "number",
      default: 0.24,
      min: 0.01,
      max: 1,
      label: "Highlight softness"
    },
    highlightStrength: {
      type: "number",
      default: 0.62,
      min: 0,
      max: 1.5,
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
      default: 0.94,
      min: 0.1,
      max: 1,
      label: "Water opacity"
    },
    emissiveStrength: {
      type: "number",
      default: 0.2,
      min: 0,
      max: 2,
      label: "Surface glow"
    },
    roughness: {
      type: "number",
      default: 0.18,
      min: 0,
      max: 1,
      label: "Roughness"
    },
    metalness: {
      type: "number",
      default: 0.02,
      min: 0,
      max: 1,
      label: "Metalness"
    }
  },
  build({ material, inputs, parameters }) {
    const phase = time.mul(parameters.waveSpeed);
    const coordinates = uv();
    const scaledCoordinates = coordinates.mul(parameters.textureScale);
    const warpX = sin(
      coordinates.y
        .mul(parameters.distortionScale)
        .add(phase.mul(0.55))
    ).mul(parameters.distortionAmount);
    const warpY = sin(
      coordinates.x
        .mul(parameters.distortionScale.mul(1.17))
        .sub(phase.mul(0.43))
    ).mul(parameters.distortionAmount);

    const textureUvA = vec2(
      fract(scaledCoordinates.x.add(phase.mul(0.032)).add(warpX)),
      fract(scaledCoordinates.y.sub(phase.mul(0.021)).add(warpY))
    );
    const textureUvB = vec2(
      fract(scaledCoordinates.x.sub(phase.mul(0.024)).sub(warpY.mul(0.7))),
      fract(scaledCoordinates.y.add(phase.mul(0.029)).add(warpX.mul(0.7)))
    );
    const textureSampleA = texture(parameters.causticTexture, textureUvA);
    const textureSampleB = texture(parameters.causticTexture, textureUvB);
    const sampledColor = vec3(
      textureSampleA.x.mul(0.58).add(textureSampleB.x.mul(0.42)),
      textureSampleA.y.mul(0.58).add(textureSampleB.y.mul(0.42)),
      textureSampleA.z.mul(0.58).add(textureSampleB.z.mul(0.42))
    );
    const luminance = sampledColor.x
      .mul(0.2126)
      .add(sampledColor.y.mul(0.7152))
      .add(sampledColor.z.mul(0.0722))
      .saturate();
    const highlightMask = smoothstep(
      parameters.highlightThreshold,
      parameters.highlightThreshold.add(parameters.highlightSoftness),
      luminance
    );
    const tintedWater = mix(
      parameters.deepColor,
      parameters.shallowColor,
      luminance
    );
    const texturedWater = mix(
      tintedWater,
      sampledColor,
      parameters.textureStrength
    );
    const waterColor = mix(
      texturedWater,
      parameters.highlightColor,
      highlightMask.mul(parameters.highlightStrength).saturate()
    );

    const vertexWave = sin(
      positionLocal.x.mul(parameters.vertexScale).add(phase)
    ).add(
      sin(
        positionLocal.y
          .mul(parameters.vertexScale.mul(1.21))
          .sub(phase.mul(0.61))
      )
    );
    const displacement = vertexWave.mul(parameters.vertexAmplitude);

    material.positionNode = positionLocal.add(normalLocal.mul(displacement));
    material.colorNode = mix(inputs.baseColor, waterColor, parameters.colorStrength);
    material.emissiveNode = inputs.emissive.add(
      parameters.highlightColor
        .mul(highlightMask)
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
