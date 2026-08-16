import { defineMaterial } from "@gdevelop/tsl";
import { mix, sin, time } from "three/tsl";

export default defineMaterial({
  apiVersion: 1,
  base: "inherit",
  label: "Sun Flicker",
  description: "Warm, time-driven flicker for collectible sun meshes.",
  parameters: {
    flickerColor: {
      type: "color",
      default: "#FFD54A",
      label: "Flicker color"
    },
    flickerStrength: {
      type: "number",
      default: 0.7,
      min: 0,
      max: 1,
      label: "Flicker strength"
    },
    flickerSpeed: {
      type: "number",
      default: 7,
      min: 0,
      max: 20,
      label: "Flicker speed"
    },
    emissiveStrength: {
      type: "number",
      default: 1.35,
      min: 0,
      max: 4,
      label: "Emissive strength"
    }
  },
  build({ material, inputs, parameters }) {
    const pulse = sin(time.mul(parameters.flickerSpeed))
      .mul(0.35)
      .add(sin(time.mul(parameters.flickerSpeed).mul(1.73)).mul(0.15))
      .add(0.5);
    const flickerMix = pulse.mul(parameters.flickerStrength);
    const flickerLight = parameters.flickerColor
      .mul(pulse)
      .mul(parameters.emissiveStrength);

    material.colorNode = mix(inputs.baseColor, parameters.flickerColor, flickerMix);
    material.emissiveNode = inputs.emissive.add(flickerLight);
  }
});
