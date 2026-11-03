import AsyncStorage from "@react-native-async-storage/async-storage";
import * as SecureStore from "expo-secure-store";
import { Platform } from "react-native";

export async function writeGuestToken(key: string, token: string): Promise<void> {
  if (Platform.OS === "web") {
    await AsyncStorage.setItem(key, token);
    return;
  }
  await SecureStore.setItemAsync(key, token);
}

export async function writeAuthToken(key: string, token: string): Promise<void> {
  await writeGuestToken(key, token);
}

export async function readGuestToken(key: string): Promise<string | null> {
  if (Platform.OS === "web") return AsyncStorage.getItem(key);
  return SecureStore.getItemAsync(key);
}

export async function readAuthToken(key: string): Promise<string | null> {
  return readGuestToken(key);
}

export async function removeGuestToken(key: string): Promise<void> {
  if (Platform.OS === "web") {
    await AsyncStorage.removeItem(key);
    return;
  }
  await SecureStore.deleteItemAsync(key);
}

export async function removeAuthToken(key: string): Promise<void> {
  await removeGuestToken(key);
}
